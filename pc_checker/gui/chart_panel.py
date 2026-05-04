from __future__ import annotations

from typing import Any

import customtkinter as ctk
import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class LiveTrendChart(ctk.CTkFrame):
    """CPU and RAM % history (0–100) on a shared time axis."""

    def __init__(self, master: Any, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._fig = Figure(figsize=(7.2, 2.4), dpi=100)
        self._fig.patch.set_facecolor("#1a1a1a")
        self._ax = self._fig.add_subplot(111)
        self._ax.set_facecolor("#1e1e1e")
        self._ax.set_ylim(0, 100)
        self._ax.set_ylabel("%")
        self._ax.grid(True, alpha=0.25, color="#555555")
        self._ax.tick_params(colors="#cccccc", labelsize=8)
        for spine in self._ax.spines.values():
            spine.set_color("#444444")

        # Must not use "_canvas" — CTkFrame reserves that for its own Tk canvas.
        self._mpl_canvas = FigureCanvasTkAgg(self._fig, self)
        self._mpl_canvas.get_tk_widget().pack(fill="both", expand=True)

    def set_history(self, cpu: list[float], ram: list[float]) -> None:
        self._ax.clear()
        self._ax.set_facecolor("#1e1e1e")
        self._ax.set_ylim(0, 100)
        self._ax.set_ylabel("%")
        self._ax.grid(True, alpha=0.25, color="#555555")
        self._ax.tick_params(colors="#cccccc", labelsize=8)
        n = min(len(cpu), len(ram))
        if n < 2:
            self._ax.text(0.5, 0.5, "Collecting samples…", ha="center", va="center", color="#888888", transform=self._ax.transAxes)
        else:
            xs = list(range(n))
            self._ax.plot(xs, cpu[-n:], color="#3498db", linewidth=1.4, label="CPU %")
            self._ax.plot(xs, ram[-n:], color="#e67e22", linewidth=1.2, label="RAM %")
            self._ax.legend(loc="upper right", fontsize=8, facecolor="#2b2b2b", edgecolor="#444444", labelcolor="#eeeeee")
        self._mpl_canvas.draw_idle()
