# Compresseur de PDF

Application locale (aucune donnée envoyée sur Internet) pour compresser des PDF :
un fichier, plusieurs fichiers ou tout le contenu d'un dossier. Les fichiers
compressés gardent le même nom et sont écrits dans un dossier de sortie ; les
originaux ne sont jamais modifiés.

## Télécharger

Rendez-vous dans l'onglet **Releases** et téléchargez le fichier adapté :

| Système | Fichier |
|---|---|
| Mac avec puce Intel | `Compresseur-PDF-Mac-Intel.zip` |
| Mac avec puce Apple (M1, M2, M3…) | `Compresseur-PDF-Mac-Apple-Silicon.zip` |
| Windows 10 / 11 | `Compresseur-PDF-Windows.zip` |

(Sur Mac : menu Pomme › « À propos de ce Mac » indique la puce.)

## Premier lancement

Les applications ne sont pas signées, votre système affichera un avertissement.

- **Mac** : dézippez, glissez l'application dans *Applications*, puis clic droit › **Ouvrir** › confirmez.
  Si besoin : Réglages Système › Confidentialité et sécurité › **Ouvrir quand même**.
- **Windows** : dézippez le dossier en entier, lancez `Compresseur PDF.exe`.
  Si « Windows a protégé votre PC » apparaît : **Informations complémentaires** › **Exécuter quand même**.

## Utilisation

1. Ajoutez des fichiers ou un dossier.
2. Choisissez le niveau de compression (« Moyen » recommandé).
3. Vérifiez le dossier de sortie, puis lancez la compression.

## Lancer depuis le code

```
pip install -r requirements.txt
python compresseur_pdf.py
```
