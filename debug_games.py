import sys, os, traceback
sys.path.insert(0, os.path.join(os.getcwd(), "source"))
import customtkinter as ctk
ctk.set_appearance_mode("dark")
from ui.games_page import GamesPage

root = ctk.CTk()
root.geometry("1200x800")
try:
    gp = GamesPage(root, on_games_changed=lambda: None, on_back=lambda: None)
    gp.pack(fill="both", expand=True)
    root.update()
    print("GAMES PAGE OK")
except Exception:
    traceback.print_exc()
finally:
    root.after(300, root.destroy)
    try:
        root.mainloop()
    except Exception:
        traceback.print_exc()
