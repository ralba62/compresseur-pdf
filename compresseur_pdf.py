#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compresseur de PDF – 100 % local, aucune donnée n'est envoyée sur Internet.

Installation (une seule fois) :
    pip install pypdf pillow

Lancement :
    python compresseur_pdf.py

Fonctions :
    - Ajouter un ou plusieurs fichiers PDF
    - Ajouter tout le contenu d'un dossier (avec ou sans sous-dossiers)
    - Export en PDF avec le MÊME NOM de fichier, dans un dossier de sortie
      (les originaux ne sont jamais modifiés)
"""

import io
import os
import sys
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    PdfReader = PdfWriter = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pypdf as _pypdf
    PYPDF_VERSION = _pypdf.__version__
except Exception:
    PYPDF_VERSION = "absent"
try:
    import PIL as _pil
    PIL_VERSION = _pil.__version__
except Exception:
    PIL_VERSION = "ABSENT"

if Image is not None:
    Image.MAX_IMAGE_PIXELS = None  # scans très haute résolution

# Niveaux de compression : (résolution cible des images en dpi, qualité JPEG)
# None -> compression sans perte uniquement (images non modifiées)
NIVEAUX = {
    "Léger – sans perte de qualité": (None, None),
    "Moyen – images 150 dpi (recommandé)": (150, 75),
    "Fort – images 110 dpi": (110, 60),
    "Maximum – images 72 dpi": (72, 45),
}


def _res(v):
    """Résout une référence indirecte pypdf (sans dépendre de la version)."""
    return v.get_object() if hasattr(v, "get_object") else v


def _liste_filtres(obj):
    f = _res(obj.get("/Filter"))
    if f is None:
        return []
    if isinstance(f, (list, tuple)):
        return [str(_res(x)) for x in f]
    return [str(f)]


def _nb_composantes(obj):
    cs = _res(obj.get("/ColorSpace"))
    if cs is None:
        return None
    if isinstance(cs, (list, tuple)):
        nom = str(_res(cs[0]))
        if nom == "/ICCBased":
            try:
                return int(_res(_res(cs[1])["/N"]))
            except Exception:
                return None
        return {"/CalRGB": 3, "/CalGray": 1}.get(nom)
    return {"/DeviceRGB": 3, "/DeviceGray": 1}.get(str(cs))


def _parcourir_images(resources, vus, profondeur=0):
    """Renvoie (dictionnaire_xobjects, nom, objet_image) pour chaque image."""
    resources = _res(resources)
    if resources is None:
        return
    xobj = _res(resources.get("/XObject"))
    if xobj is None:
        return
    for nom in list(xobj.keys()):
        obj = _res(xobj[nom])
        sous_type = str(_res(obj.get("/Subtype")))
        if sous_type == "/Image":
            yield xobj, nom, obj
        elif sous_type == "/Form" and profondeur < 2:
            if id(obj) in vus:
                continue
            vus.add(id(obj))
            yield from _parcourir_images(obj.get("/Resources"), vus, profondeur + 1)


def _taille_origine(obj):
    try:
        return int(_res(obj.get("/Length")))
    except Exception:
        return len(obj.get_data())


def _recompresser_images(writer, dpi, qualite):
    from pypdf.generic import DecodedStreamObject, NameObject, NumberObject

    stats = {"trouvees": 0, "reduites": 0, "erreur": "", "formats": set()}
    deja = {}  # id(objet image) -> nouvelle référence (images partagées)
    vus = set()
    ignores = ("/Filter", "/DecodeParms", "/Length", "/Width", "/Height",
               "/BitsPerComponent", "/DL")

    for page in writer.pages:
        try:
            cible = max(float(page.mediabox.width), float(page.mediabox.height)) / 72 * dpi
        except Exception:
            cible = 842 / 72 * dpi

        for xobj, nom, obj in list(_parcourir_images(page.get("/Resources"), vus)):
            try:
                if id(obj) in deja:
                    xobj[nom] = deja[id(obj)]
                    continue
                stats["trouvees"] += 1

                filtres = _liste_filtres(obj)
                n = _nb_composantes(obj)
                bpc = _res(obj.get("/BitsPerComponent"))
                w = int(_res(obj["/Width"]))
                h = int(_res(obj["/Height"]))
                stats["formats"].add(f"{'+'.join(filtres) or 'brut'} {bpc}bits {n}c")

                if obj.get("/Mask") is not None or n not in (1, 3):
                    continue
                # les filtres texte (ASCII85...) sont décodés par get_data()
                filtres = [f for f in filtres if f not in ("/ASCII85Decode", "/ASCIIHexDecode")]

                echelle = min(1.0, cible / max(w, h))
                tw, th = max(1, round(w * echelle)), max(1, round(h * echelle))

                if filtres == ["/DCTDecode"]:
                    pil = Image.open(io.BytesIO(obj.get_data()))
                    if pil.mode not in ("RGB", "L"):
                        continue
                    if echelle < 1.0:
                        try:
                            pil.draft(pil.mode, (tw, th))  # décodage rapide à taille réduite
                        except Exception:
                            pass
                    pil.load()
                elif filtres in ([], ["/FlateDecode"]) and int(bpc or 8) == 8:
                    donnees = obj.get_data()
                    if len(donnees) != w * h * n:
                        continue
                    pil = Image.frombytes("RGB" if n == 3 else "L", (w, h), donnees)
                else:
                    continue

                if pil.size != (tw, th):
                    pil = pil.resize((tw, th), Image.LANCZOS)

                sortie = io.BytesIO()
                pil.save(sortie, "JPEG", quality=qualite, optimize=True)
                jpeg = sortie.getvalue()
                if len(jpeg) >= 0.9 * _taille_origine(obj):
                    continue  # gain insuffisant : on laisse l'image telle quelle

                nouveau = DecodedStreamObject()
                nouveau.set_data(jpeg)
                for cle, val in obj.items():
                    if str(cle) not in ignores:
                        nouveau[NameObject(str(cle))] = val
                nouveau[NameObject("/Filter")] = NameObject("/DCTDecode")
                nouveau[NameObject("/Width")] = NumberObject(pil.size[0])
                nouveau[NameObject("/Height")] = NumberObject(pil.size[1])
                nouveau[NameObject("/BitsPerComponent")] = NumberObject(8)

                ajouter = getattr(writer, "add_object", None) or writer._add_object
                ref = ajouter(nouveau)
                xobj[nom] = ref
                deja[id(obj)] = ref
                stats["reduites"] += 1
            except Exception as e:
                stats["erreur"] = f"{type(e).__name__}: {e}"
                continue
    return stats


def _ecrire(writer, chemin):
    with open(chemin, "wb") as f:
        writer.write(f)
    return chemin.stat().st_size


def compresser_pdf(src: Path, dst: Path, dpi, qualite):
    """Compresse src vers dst. Retourne (taille_avant, taille_apres, info)."""
    avant = src.stat().st_size
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")

    reader = PdfReader(str(src))
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            raise RuntimeError("fichier protégé par mot de passe")

    writer = PdfWriter(clone_from=reader)

    info = ""
    st = None
    if dpi and Image is not None:
        st = _recompresser_images(writer, dpi, qualite)
        if st["trouvees"] == 0:
            info = "aucune image trouvée dans ce PDF"
        else:
            info = f"{st['reduites']} image(s) réduite(s) sur {st['trouvees']}"
            if st["reduites"] == 0:
                info += " – formats : " + ", ".join(sorted(st["formats"]))[:150]
        if st["erreur"]:
            info += f" (erreur : {st['erreur'][:120]})"

    for page in writer.pages:
        try:
            page.compress_content_streams()
        except Exception:
            pass
    try:
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    except Exception:
        pass

    apres = _ecrire(writer, tmp)

    # Si des images ont été réduites mais que l'ancien contenu est resté dans
    # le fichier, on reconstruit un PDF propre à partir des seules pages utiles.
    if st and st["reduites"] > 0 and apres > 0.9 * avant:
        try:
            propre = PdfWriter()
            for page in writer.pages:
                propre.add_page(page)
            tmp2 = dst.with_name(dst.name + ".tmp2")
            taille2 = _ecrire(propre, tmp2)
            if taille2 < apres:
                os.replace(tmp2, tmp)
                apres = taille2
            else:
                tmp2.unlink(missing_ok=True)
        except Exception:
            pass

    if apres >= avant:
        tmp.unlink(missing_ok=True)
        shutil.copy2(src, dst)
        apres = avant
        info = (info + " – " if info else "") + "déjà optimisé, copié tel quel"
    else:
        os.replace(tmp, dst)
    return avant, apres, info


def fmt(octets):
    for unite in ("o", "Ko", "Mo", "Go"):
        if octets < 1024:
            return f"{octets:.0f} {unite}" if unite == "o" else f"{octets:.1f} {unite}"
        octets /= 1024
    return f"{octets:.1f} To"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Compresseur PDF")
        self.geometry("820x640")
        self.minsize(700, 540)

        # Liste de tuples (chemin_source, chemin_relatif_de_sortie)
        self.items = []
        self.q = queue.Queue()
        self.travail = False

        self.var_niveau = tk.StringVar(value=list(NIVEAUX)[1])
        self.var_sortie = tk.StringVar()
        self.var_recursif = tk.BooleanVar(value=True)

        self._construire()
        self.after(100, self._lire_queue)
        self.lift()
        self.attributes('-topmost', True)
        self.after(300, lambda: self.attributes('-topmost', False))

    # ------------------------------------------------------------ interface
    def _construire(self):
        pad = {"padx": 10, "pady": 5}

        # --- Sélection
        cadre = ttk.LabelFrame(self, text="1. Choisir les PDF")
        cadre.pack(fill="both", expand=True, **pad)

        barre = ttk.Frame(cadre)
        barre.pack(fill="x", padx=8, pady=6)
        ttk.Button(barre, text="Ajouter des fichiers…", command=self.ajouter_fichiers).pack(side="left")
        ttk.Button(barre, text="Ajouter un dossier…", command=self.ajouter_dossier).pack(side="left", padx=6)
        ttk.Checkbutton(barre, text="Inclure les sous-dossiers", variable=self.var_recursif).pack(side="left", padx=6)
        ttk.Button(barre, text="Vider", command=self.vider).pack(side="right")
        ttk.Button(barre, text="Retirer la sélection", command=self.retirer).pack(side="right", padx=6)

        zone = ttk.Frame(cadre)
        zone.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.liste = tk.Listbox(zone, selectmode="extended", activestyle="none")
        sb = ttk.Scrollbar(zone, orient="vertical", command=self.liste.yview)
        self.liste.configure(yscrollcommand=sb.set)
        self.liste.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.lbl_compte = ttk.Label(cadre, text="Aucun fichier")
        self.lbl_compte.pack(anchor="w", padx=10, pady=(0, 6))

        # --- Options
        opt = ttk.LabelFrame(self, text="2. Options")
        opt.pack(fill="x", **pad)
        opt.columnconfigure(1, weight=1)

        ttk.Label(opt, text="Compression :").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(opt, textvariable=self.var_niveau, values=list(NIVEAUX),
                     state="readonly").grid(row=0, column=1, columnspan=2, sticky="ew", padx=8)

        ttk.Label(opt, text="Dossier de sortie :").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(opt, textvariable=self.var_sortie).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(opt, text="Parcourir…", command=self.choisir_sortie).grid(row=1, column=2, padx=8)

        ttk.Label(
            opt,
            text="Les fichiers compressés gardent le même nom. Les originaux ne sont jamais modifiés.",
            foreground="#666",
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6))

        # --- Lancer
        act = ttk.LabelFrame(self, text="3. Compresser")
        act.pack(fill="both", expand=True, **pad)

        haut = ttk.Frame(act)
        haut.pack(fill="x", padx=8, pady=6)
        self.btn = ttk.Button(haut, text="Lancer la compression", command=self.lancer)
        self.btn.pack(side="left")
        self.barre = ttk.Progressbar(haut, mode="determinate")
        self.barre.pack(side="left", fill="x", expand=True, padx=10)

        self.journal = tk.Text(act, height=8, state="disabled", wrap="none")
        self.journal.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # ------------------------------------------------------------ sélection
    def _ajouter(self, src: Path, rel: Path):
        if any(s == src for s, _ in self.items):
            return
        self.items.append((src, rel))
        self.liste.insert("end", str(src))

    def _maj_compte(self):
        n = len(self.items)
        self.lbl_compte.config(text="Aucun fichier" if n == 0 else f"{n} fichier(s) PDF")

    def ajouter_fichiers(self):
        chemins = filedialog.askopenfilenames(
            title="Choisir des fichiers PDF", filetypes=[("PDF", "*.pdf *.PDF")]
        )
        for c in chemins:
            p = Path(c)
            self._ajouter(p, Path(p.name))
        self._auto_sortie()
        self._maj_compte()

    def ajouter_dossier(self):
        d = filedialog.askdirectory(title="Choisir un dossier")
        if not d:
            return
        racine = Path(d)
        motif = racine.rglob("*") if self.var_recursif.get() else racine.glob("*")
        trouves = sorted(p for p in motif if p.is_file() and p.suffix.lower() == ".pdf")
        if not trouves:
            messagebox.showinfo("Dossier vide", "Aucun PDF trouvé dans ce dossier.")
            return
        for p in trouves:
            # on conserve l'arborescence relative pour éviter les collisions de noms
            self._ajouter(p, p.relative_to(racine))
        self._auto_sortie(racine.parent / (racine.name + "_compressé"))
        self._maj_compte()

    def retirer(self):
        for i in reversed(self.liste.curselection()):
            self.liste.delete(i)
            del self.items[i]
        self._maj_compte()

    def vider(self):
        self.liste.delete(0, "end")
        self.items.clear()
        self._maj_compte()

    def _auto_sortie(self, defaut: Path = None):
        if self.var_sortie.get() or not self.items:
            return
        if defaut is None:
            defaut = self.items[0][0].parent / "PDF_compressés"
        self.var_sortie.set(str(defaut))

    def choisir_sortie(self):
        d = filedialog.askdirectory(title="Dossier de sortie")
        if d:
            self.var_sortie.set(d)

    # ------------------------------------------------------------ traitement
    def log(self, texte):
        self.journal.config(state="normal")
        self.journal.insert("end", texte + "\n")
        self.journal.see("end")
        self.journal.config(state="disabled")

    def lancer(self):
        if self.travail:
            return
        if PdfReader is None:
            messagebox.showerror("Module manquant", "Installez pypdf :\n\npip install pypdf pillow")
            return
        if not self.items:
            messagebox.showwarning("Aucun fichier", "Ajoutez au moins un PDF.")
            return
        if not self.var_sortie.get().strip():
            messagebox.showwarning("Dossier de sortie", "Choisissez un dossier de sortie.")
            return

        sortie = Path(self.var_sortie.get().strip())
        dpi, qualite = NIVEAUX[self.var_niveau.get()]
        taches = list(self.items)

        self.travail = True
        self.btn.config(state="disabled")
        self.barre.config(maximum=len(taches), value=0)
        self.journal.config(state="normal")
        self.journal.delete("1.0", "end")
        self.journal.config(state="disabled")
        self.log(f"Python {sys.version.split()[0]} | pypdf {PYPDF_VERSION} | Pillow {PIL_VERSION}")
        self.log(f"Sortie : {sortie}\n")
        if dpi and Image is None:
            self.log("⚠ Pillow n'est pas installé : compression sans perte uniquement.\n"
                     "  (pip install pillow pour réduire aussi les images)\n")

        threading.Thread(
            target=self._worker, args=(taches, sortie, dpi, qualite), daemon=True
        ).start()

    def _worker(self, taches, sortie, dpi, qualite):
        total_avant = total_apres = 0
        erreurs = 0
        for i, (src, rel) in enumerate(taches, 1):
            dst = sortie / rel
            try:
                if dst.resolve() == src.resolve():
                    raise RuntimeError("le dossier de sortie est celui du fichier source")
                avant, apres, info = compresser_pdf(src, dst, dpi, qualite)
                total_avant += avant
                total_apres += apres
                gain = (1 - apres / avant) * 100 if avant else 0
                self.q.put(("log", f"✔ {rel}  {fmt(avant)} → {fmt(apres)}  (−{gain:.0f} %)  {info}"))
            except Exception as e:
                erreurs += 1
                self.q.put(("log", f"✘ {rel} : {e}"))
            self.q.put(("progress", i))

        if total_avant:
            gain = (1 - total_apres / total_avant) * 100
            self.q.put(("log", f"\nTerminé : {fmt(total_avant)} → {fmt(total_apres)} (−{gain:.0f} %)"))
        if erreurs:
            self.q.put(("log", f"{erreurs} fichier(s) en erreur."))
        self.q.put(("done", str(sortie)))

    def _lire_queue(self):
        try:
            while True:
                type_, val = self.q.get_nowait()
                if type_ == "log":
                    self.log(val)
                elif type_ == "progress":
                    self.barre.config(value=val)
                elif type_ == "done":
                    self.travail = False
                    self.btn.config(state="normal")
                    if messagebox.askyesno("Terminé", "Compression terminée.\nOuvrir le dossier de sortie ?"):
                        self._ouvrir(val)
        except queue.Empty:
            pass
        self.after(100, self._lire_queue)

    @staticmethod
    def _ouvrir(dossier):
        try:
            if os.name == "nt":
                os.startfile(dossier)
            elif os.uname().sysname == "Darwin":
                os.system(f'open "{dossier}"')
            else:
                os.system(f'xdg-open "{dossier}"')
        except Exception:
            pass


if __name__ == "__main__":
    App().mainloop()
