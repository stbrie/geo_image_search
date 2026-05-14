"""
Tkinter GUI for geo_image_search.

Runs the same search engine the CLI uses, in a background thread.
stdout/stderr from the search is streamed into a scrolling log via
contextlib.redirect_stdout; Cancel works by setting a threading.Event the
core checks during the file walk.
"""

from __future__ import annotations

import contextlib
import io
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import geo_image_search

HELP_FILE = Path(__file__).resolve().parent / "HELP.md"
SETTINGS_FILE = Path.home() / ".geo_image_search_gui.json"

# Keys persisted in SETTINGS_FILE. Mix of strings (paths, radius) and bools
# (option flags). Keys must match App.vars so values can be poked straight in.
_SETTINGS_KEYS: tuple[str, ...] = (
    "root", "output_directory", "radius", "cluster_radius",
    "copy_files", "save_addresses", "verbose", "far",
    "resume", "export_kml", "sort_by_location", "overwrite",
    "single_location",
)


def _load_settings() -> dict:
    """Return the saved defaults, or {} if the file is missing/unreadable."""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: data[k] for k in _SETTINGS_KEYS if k in data}


def _save_settings(data: dict) -> None:
    """Write the given defaults to SETTINGS_FILE (atomic via temp + replace)."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(SETTINGS_FILE.suffix + ".tmp")
    payload = {k: data[k] for k in _SETTINGS_KEYS if k in data}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(SETTINGS_FILE)


class _QueueWriter(io.TextIOBase):
    """File-like object whose writes are pushed into a thread-safe queue."""

    def __init__(self, q: queue.Queue) -> None:
        self._q = q

    def writable(self) -> bool:  # noqa: D401
        return True

    def write(self, s: str) -> int:
        if s:
            self._q.put(s)
        return len(s)


# Form field definitions. Order is preserved.
# Each tuple: (gui_key, label, --flag, default, emit_when_unchecked)
#   - default:              initial BooleanVar value
#   - emit_when_unchecked:  if True, append --flag when the box is OFF
#                           (used for "Copy files" which maps to --find_only)
_BOOL_FIELDS: list[tuple[str, str, str, bool, bool]] = [
    ("copy_files", "Copy files to output directory", "--find_only", True, True),
    ("save_addresses", "Save addresses to CSV (requires output dir)", "--save_addresses", False, False),
    ("verbose", "Verbose output", "--verbose", False, False),
    ("far", "Also show images outside radius", "--far", False, False),
    ("resume", "Resume from previous checkpoint", "--resume", False, False),
    ("export_kml", "Export KML for Google Earth", "--export-kml", False, False),
    ("sort_by_location", "Sort by location (cluster into folders)", "--sort-by-location", False, False),
    ("overwrite", "Overwrite existing files (don't auto-rename)", "--overwrite", False, False),
    ("single_location", "Single location (one nested folder; needs address or lat/lon)", "--single-location", False, False),
]

# Bool keys that are mutually exclusive — only one may be checked at a time.
# Rendered on their own row with an "— OR —" label, and a write trace keeps
# the other disabled while one is selected.
_MUTEX_PAIR: tuple[str, str] = ("sort_by_location", "single_location")

# Form rows. Each row is (kind, [field, ...]):
#   "wide"   — one field spanning the full width (optionally with a Browse button)
#   "narrow" — one short field, left-aligned (rest of the row left blank)
#   "pair"   — two short fields side-by-side
# Field tuple: (gui_key, label, cli_flag, browse_kind)
#   browse_kind: None | "dir" | "file"
_FORM_ROWS: list[tuple[str, list[tuple[str, str, str, str | None]]]] = [
    ("wide", [("address", "Address", "--address", None)]),
    ("pair", [
        ("latitude", "Latitude (decimal)", "--latitude", None),
        ("date_from", "Date from (YYYY-MM-DD)", "--date-from", None),
    ]),
    ("pair", [
        ("longitude", "Longitude (decimal)", "--longitude", None),
        ("date_to", "Date to (YYYY-MM-DD)", "--date-to", None),
    ]),
    ("pair", [
        ("radius", "Radius (miles)", "--radius", None),
        ("cluster_radius", "Cluster radius (yd)", "--cluster-radius", None),
    ]),
    ("wide", [("root", "Images root directory", "--root", "dir")]),
    ("wide", [("output_directory", "Output directory", "--output_directory", "dir")]),
]

# Flattened view used by _build_argv.
_STR_FIELDS: list[tuple[str, str, str, str | None]] = [
    field for _kind, fields in _FORM_ROWS for field in fields
]

# Width (in characters) for entries on "pair" / "narrow" rows.
_SHORT_WIDTH = 14

# Initial values for form fields, used when no saved setting overrides them.
# Keep in sync with argparse defaults in geo_image_search.py.
_FIELD_DEFAULTS: dict[str, str] = {
    "radius": "0.05",
}


class App:
    POLL_MS = 100

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Geo Image Search")
        root.geometry("820x760")
        root.minsize(640, 520)

        self.cancel_event: threading.Event | None = None
        self.worker: threading.Thread | None = None
        self.out_q: queue.Queue = queue.Queue()
        self.vars: dict[str, tk.Variable] = {}
        self.entries: dict[str, ttk.Entry] = {}
        self.bool_widgets: dict[str, ttk.Checkbutton] = {}

        self._save_after_id: str | None = None

        self._build_menu()
        self._build()
        self._apply_defaults()
        self._wire_autosave()
        self._wire_exclusions()
        self._wire_mutex_exclusion()
        self._poll()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        settings_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Preferences…", command=self.show_preferences)
        settings_menu.add_separator()
        settings_menu.add_command(label="Clear geocode cache…", command=self.on_clear_geocode_cache)

        help_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Field reference…", command=self.show_help)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)

    def _apply_defaults(self) -> None:
        """Pre-populate form fields from saved defaults (called once at startup)."""
        for key, value in _load_settings().items():
            if key in self.vars:
                self.vars[key].set(value)

    def _wire_autosave(self) -> None:
        """Persist settings on every change to a tracked field (debounced)."""
        for key in _SETTINGS_KEYS:
            if key in self.vars:
                self.vars[key].trace_add("write", lambda *_a: self._schedule_save())

    def _schedule_save(self) -> None:
        if self._save_after_id is not None:
            try:
                self.root.after_cancel(self._save_after_id)
            except tk.TclError:
                pass
        self._save_after_id = self.root.after(500, self._do_save)

    def _do_save(self) -> None:
        self._save_after_id = None
        data = {k: self.vars[k].get() for k in _SETTINGS_KEYS if k in self.vars}
        try:
            _save_settings(data)
        except OSError:
            pass  # non-critical; user can retry by changing any field

    def _wire_exclusions(self) -> None:
        """Make Address and Latitude/Longitude mutually exclusive."""
        for key in ("address", "latitude", "longitude"):
            self.vars[key].trace_add("write", lambda *_a: self._update_exclusions())
        self._update_exclusions()

    def _update_exclusions(self) -> None:
        has_addr = bool(str(self.vars["address"].get()).strip())
        has_coords = bool(str(self.vars["latitude"].get()).strip()) or bool(
            str(self.vars["longitude"].get()).strip()
        )
        self.entries["address"].configure(state="disabled" if has_coords else "normal")
        state = "disabled" if has_addr else "normal"
        self.entries["latitude"].configure(state=state)
        self.entries["longitude"].configure(state=state)

    def _wire_mutex_exclusion(self) -> None:
        """Disable one of the mutex-paired checkboxes when the other is on."""
        for key in _MUTEX_PAIR:
            self.vars[key].trace_add("write", lambda *_a: self._update_mutex())
        self._update_mutex()

    def _update_mutex(self) -> None:
        a, b = _MUTEX_PAIR
        va = bool(self.vars[a].get())
        vb = bool(self.vars[b].get())
        # Defensive: if a hand-edited settings file turned both on, clear
        # the first. The re-fired trace settles state.
        if va and vb:
            self.vars[a].set(False)
            return
        self.bool_widgets[a].configure(state="disabled" if vb else "normal")
        self.bool_widgets[b].configure(state="disabled" if va else "normal")

    def show_preferences(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Preferences")
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(
            frame,
            text="Defaults used as starting values for each new search.\n"
            "Leave blank to skip. Changes apply on next launch and to\n"
            "any currently-blank fields in the form.",
            foreground="gray",
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        current = _load_settings()
        dvars: dict[str, tk.StringVar] = {}

        def add_field(row: int, label: str, key: str, browse_kind: str) -> None:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=4)
            var = tk.StringVar(value=current.get(key, ""))
            dvars[key] = var
            ttk.Entry(frame, textvariable=var, width=44).grid(
                row=row, column=1, sticky="we", padx=4, pady=4
            )

            def browse() -> None:
                start = var.get() or None
                if browse_kind == "dir":
                    p = filedialog.askdirectory(initialdir=start, parent=win)
                else:
                    p = filedialog.askopenfilename(
                        initialdir=start,
                        parent=win,
                        filetypes=[("TOML", "*.toml"), ("All files", "*.*")],
                    )
                if p:
                    var.set(p)

            ttk.Button(frame, text="Browse…", command=browse).grid(
                row=row, column=2, padx=4, pady=4
            )

        add_field(1, "Images root", "root", "dir")
        add_field(2, "Output directory", "output_directory", "dir")

        btnrow = ttk.Frame(frame)
        btnrow.grid(row=4, column=0, columnspan=3, sticky="e", pady=(8, 0))

        def on_save() -> None:
            new_settings = {k: v.get().strip() for k, v in dvars.items()}
            # Merge with existing so auto-saved options/radius aren't wiped.
            merged = _load_settings()
            merged.update(new_settings)
            try:
                _save_settings(merged)
            except OSError as e:
                messagebox.showerror(
                    "Preferences", f"Could not save settings:\n{e}", parent=win
                )
                return
            # Update form fields (auto-save will catch up on its next debounce).
            for k, v in new_settings.items():
                if k in self.vars:
                    self.vars[k].set(v)
            win.destroy()

        ttk.Button(btnrow, text="Cancel", command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(btnrow, text="Save", command=on_save).pack(side=tk.RIGHT, padx=(0, 4))

    def show_help(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Geo Image Search — Help")
        win.geometry("760x640")
        win.transient(self.root)

        try:
            content = HELP_FILE.read_text(encoding="utf-8")
        except OSError as e:
            content = f"Could not load help file at {HELP_FILE}:\n\n{e}"

        frame = ttk.Frame(win, padding=4)
        frame.pack(fill=tk.BOTH, expand=True)
        txt = tk.Text(frame, wrap="word", font=("Consolas", 10))
        ysb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=ysb.set)
        txt.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        txt.insert("1.0", content)
        # Simple header styling: lines followed by ==== or ----
        self._style_help(txt, content)
        txt.configure(state="disabled")

        btnrow = ttk.Frame(win, padding=(4, 0, 4, 4))
        btnrow.pack(fill=tk.X)
        ttk.Button(btnrow, text="Close", command=win.destroy).pack(side=tk.RIGHT)

    @staticmethod
    def _style_help(txt: tk.Text, content: str) -> None:
        txt.tag_configure("h1", font=("Segoe UI", 13, "bold"), spacing3=6)
        txt.tag_configure("h2", font=("Segoe UI", 11, "bold"), spacing1=8, spacing3=4)
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if i + 1 < len(lines) and lines[i + 1].startswith("==") and line.strip():
                txt.tag_add("h1", f"{i+1}.0", f"{i+1}.end")
            elif i + 1 < len(lines) and lines[i + 1].startswith("--") and line.strip():
                txt.tag_add("h2", f"{i+1}.0", f"{i+1}.end")

    def on_clear_geocode_cache(self) -> None:
        try:
            cache = geo_image_search._GeocodeCache(geo_image_search.GEOCODE_CACHE_FILE)
            count = cache.size()
        except Exception as e:
            messagebox.showerror("Geocode cache", f"Could not open cache:\n{e}")
            return
        if count == 0:
            messagebox.showinfo("Geocode cache", "Cache is already empty.")
            cache.close()
            return
        if not messagebox.askyesno(
            "Geocode cache",
            f"Clear {count} cached entries? Future searches will re-query Nominatim.",
        ):
            cache.close()
            return
        removed = cache.clear()
        cache.close()
        messagebox.showinfo("Geocode cache", f"Cleared {removed} entries.")

    def show_about(self) -> None:
        messagebox.showinfo(
            "About Geo Image Search",
            "Geo Image Search\n\n"
            "Find and organize geo-tagged JPEG images by location.\n\n"
            "https://github.com/stbrie/geo_image_search",
        )

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        # Inputs -----------------------------------------------------------
        # Grid columns:
        #   0  left label   (fixed)
        #   1  left entry   (weight=1, stretches)
        #   2  right label  (fixed; only used on "pair" rows)
        #   3  right entry  (weight=1, stretches; only used on "pair" rows)
        #   4  Browse…      (fixed; only used on "wide" rows with a browse_kind)
        form = ttk.LabelFrame(outer, text="Search parameters", padding=8)
        form.pack(fill=tk.X)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        for row, (kind, fields) in enumerate(_FORM_ROWS):
            if kind == "wide":
                key, label, _flag, browse = fields[0]
                ttk.Label(form, text=label).grid(
                    row=row, column=0, sticky="w", padx=4, pady=2
                )
                var = tk.StringVar(value=_FIELD_DEFAULTS.get(key, ""))
                self.vars[key] = var
                entry = ttk.Entry(form, textvariable=var)
                entry.grid(row=row, column=1, columnspan=3, sticky="we", padx=4, pady=2)
                self.entries[key] = entry
                if browse == "dir":
                    ttk.Button(
                        form, text="Browse…", command=lambda k=key: self._pick_dir(k)
                    ).grid(row=row, column=4, sticky="w", padx=4)
                elif browse == "file":
                    ttk.Button(
                        form, text="Browse…", command=lambda k=key: self._pick_file(k)
                    ).grid(row=row, column=4, sticky="w", padx=4)

            elif kind == "narrow":
                key, label, _flag, _browse = fields[0]
                ttk.Label(form, text=label).grid(
                    row=row, column=0, sticky="w", padx=4, pady=2
                )
                var = tk.StringVar(value=_FIELD_DEFAULTS.get(key, ""))
                self.vars[key] = var
                entry = ttk.Entry(form, textvariable=var, width=_SHORT_WIDTH)
                entry.grid(row=row, column=1, sticky="w", padx=4, pady=2)
                self.entries[key] = entry

            elif kind == "pair":
                for half, (key, label, _flag, _browse) in enumerate(fields):
                    label_col = 0 if half == 0 else 2
                    entry_col = 1 if half == 0 else 3
                    label_padx = (4, 4) if half == 0 else (16, 4)
                    ttk.Label(form, text=label).grid(
                        row=row, column=label_col, sticky="w", padx=label_padx, pady=2
                    )
                    var = tk.StringVar(value=_FIELD_DEFAULTS.get(key, ""))
                    self.vars[key] = var
                    entry = ttk.Entry(form, textvariable=var, width=_SHORT_WIDTH)
                    entry.grid(row=row, column=entry_col, sticky="w", padx=4, pady=2)
                    self.entries[key] = entry

        # Boolean options --------------------------------------------------
        opts = ttk.LabelFrame(outer, text="Options", padding=8)
        opts.pack(fill=tk.X, pady=(8, 0))

        # Regular checkboxes laid out in two columns, skipping the mutex pair.
        mutex_keys = set(_MUTEX_PAIR)
        regular_fields = [t for t in _BOOL_FIELDS if t[0] not in mutex_keys]
        for i, (key, label, _flag, default, _invert) in enumerate(regular_fields):
            var = tk.BooleanVar(value=default)
            self.vars[key] = var
            cb = ttk.Checkbutton(opts, text=label, variable=var)
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=2)
            self.bool_widgets[key] = cb

        # Mutex pair: own row, separated by "— OR —".
        mutex_row_idx = (len(regular_fields) + 1) // 2
        mutex_frame = ttk.Frame(opts)
        mutex_frame.grid(
            row=mutex_row_idx, column=0, columnspan=2, sticky="w", padx=4, pady=(8, 2)
        )
        spec_by_key = {t[0]: t for t in _BOOL_FIELDS}
        for half, key in enumerate(_MUTEX_PAIR):
            _, label, _flag, default, _invert = spec_by_key[key]
            var = tk.BooleanVar(value=default)
            self.vars[key] = var
            cb = ttk.Checkbutton(mutex_frame, text=label, variable=var)
            cb.pack(side=tk.LEFT)
            self.bool_widgets[key] = cb
            if half == 0:
                ttk.Label(
                    mutex_frame, text="  — OR —  ", foreground="gray"
                ).pack(side=tk.LEFT)

        opts.columnconfigure(0, weight=1)
        opts.columnconfigure(1, weight=1)

        # Buttons row ------------------------------------------------------
        btns = ttk.Frame(outer, padding=(0, 8))
        btns.pack(fill=tk.X)
        self.search_btn = ttk.Button(btns, text="Search", command=self.on_search)
        self.search_btn.pack(side=tk.LEFT)
        self.cancel_btn = ttk.Button(
            btns, text="Cancel", command=self.on_cancel, state="disabled"
        )
        self.cancel_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Clear log", command=self.clear_log).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Create sample config…", command=self.on_create_config).pack(
            side=tk.RIGHT
        )

        # Progress + status ------------------------------------------------
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill=tk.X)
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(outer, textvariable=self.status, anchor="w").pack(fill=tk.X, pady=(2, 4))

        # Log --------------------------------------------------------------
        logbox = ttk.LabelFrame(outer, text="Log", padding=4)
        logbox.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(logbox, height=14, wrap="none")
        ysb = ttk.Scrollbar(logbox, orient="vertical", command=self.log.yview)
        xsb = ttk.Scrollbar(logbox, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set, state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="we")
        logbox.rowconfigure(0, weight=1)
        logbox.columnconfigure(0, weight=1)

    # ---- form helpers ----------------------------------------------------

    def _pick_dir(self, key: str) -> None:
        current = self.vars[key].get() or ""
        d = filedialog.askdirectory(initialdir=current or None)
        if d:
            self.vars[key].set(d)

    def _pick_file(self, key: str) -> None:
        current = self.vars[key].get() or ""
        f = filedialog.askopenfilename(
            initialdir=current or None,
            filetypes=[("TOML", "*.toml"), ("All files", "*.*")],
        )
        if f:
            self.vars[key].set(f)

    def _build_argv(self) -> list[str]:
        argv: list[str] = []
        for key, _label, flag, _default, invert in _BOOL_FIELDS:
            checked = bool(self.vars[key].get())
            if checked is not invert:  # checked & !invert, OR unchecked & invert
                argv.append(flag)
        for key, _label, flag, _browse in _STR_FIELDS:
            v = str(self.vars[key].get()).strip()
            if v:
                argv.extend([flag, v])
        return argv

    # ---- log helpers -----------------------------------------------------

    def _append_log(self, s: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", s)
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ---- actions ---------------------------------------------------------

    def on_search(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Geo Image Search", "A search is already running.")
            return

        argv = self._build_argv()
        # Basic client-side check: root is required; without it the core
        # would print an error and exit (still visible in the log, but
        # this is friendlier).
        if not str(self.vars["root"].get()).strip():
            messagebox.showerror(
                "Geo Image Search",
                "Images root directory is required.",
            )
            return

        self._append_log(f"\n$ geo_image_search {' '.join(argv)}\n")
        self.cancel_event = threading.Event()
        self.search_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.status.set("Running…")
        self.progress.start(10)

        self.worker = threading.Thread(
            target=self._run_worker, args=(argv, self.cancel_event), daemon=True
        )
        self.worker.start()

    def on_cancel(self) -> None:
        if self.cancel_event:
            self.cancel_event.set()
            self._append_log("[cancel requested — finishing current file…]\n")
            self.status.set("Cancelling…")

    def on_create_config(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Create sample config",
            defaultextension=".toml",
            initialfile="geo_image_search.toml",
            filetypes=[("TOML", "*.toml"), ("All files", "*.*")],
        )
        if not path:
            return
        # Use the core's own sample-creator by running it in the worker pattern.
        t = threading.Thread(
            target=self._run_worker, args=(["--create-config", path], None), daemon=True
        )
        t.start()

    # ---- worker / polling ------------------------------------------------

    def _run_worker(self, argv: list[str], cancel_event: threading.Event | None) -> None:
        writer = _QueueWriter(self.out_q)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                geo_image_search.main(argv=argv, cancel_event=cancel_event)
        except SystemExit as e:
            writer.write(f"\n[exited with code {e.code}]\n")
        except Exception as e:  # surfacing any uncaught error to the user
            writer.write(f"\n[error: {e!r}]\n")
        finally:
            self.out_q.put("__DONE__")

    def _poll(self) -> None:
        cancelled = self.cancel_event is not None and self.cancel_event.is_set()
        try:
            while True:
                item = self.out_q.get_nowait()
                if item == "__DONE__":
                    self.progress.stop()
                    self.search_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self.status.set("Cancelled." if cancelled else "Done.")
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.root.after(self.POLL_MS, self._poll)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
