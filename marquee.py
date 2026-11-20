import tkinter as tk


class Marquee(tk.Canvas):
    """Scroll overflowing text without changing the underlying song title."""
    def __init__(self, parent, variable, font, bg, fg, **kwargs):
        super().__init__(parent, bg=bg, highlightthickness=0, **kwargs)
        self.variable = variable
        self.item = self.create_text(0, 0, anchor='w', font=font, fill=fg)
        self.timer = None
        self.trace = variable.trace_add('write', self.reset)
        self.bind('<Configure>', self.reset)
        self.bind('<Destroy>', self.cleanup)
        self.reset()

    def reset(self, *_):
        if self.timer:
            self.after_cancel(self.timer)
        self.itemconfigure(self.item, text=self.variable.get())
        self.coords(self.item, 4, self.winfo_height() / 2)
        bounds = self.bbox(self.item)
        self.text_width = bounds[2] - bounds[0] if bounds else 0
        if self.text_width <= self.winfo_width() - 8:
            self.coords(self.item, max(4, (self.winfo_width() - self.text_width) / 2), self.winfo_height() / 2)
            self.timer = None
        else:
            self.timer = self.after(1000, self.step)

    def step(self):
        self.move(self.item, -1, 0)
        x, _ = self.coords(self.item)
        if x + self.text_width < self.winfo_width() - 8:
            self.timer = self.after(1200, self.reset)
        else:
            self.timer = self.after(30, self.step)

    def cleanup(self, event):
        if event.widget == self:
            if self.timer:
                self.after_cancel(self.timer)
            self.variable.trace_remove('write', self.trace)
