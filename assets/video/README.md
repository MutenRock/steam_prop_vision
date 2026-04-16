# assets/video

Les fichiers vidéo ne sont **pas versionnés** (trop lourds).
Déposer les fichiers directement sur STYX dans les dossiers ci-dessous.

## Convention de nommage

```
assets/video/<nom_carte>/<nom_quelconque>.mp4
```

Le player lira **le premier .mp4 trouvé** dans le dossier de la carte détectée.
Si plusieurs fichiers sont présents, ils sont lus en **rotation aléatoire**.

## Structure attendue

```
assets/video/
├── bougie/
├── cellule/
├── chaudron/
├── dague/
└── vampire/
```

## Placeholders — sources de téléchargement

Télécharger via `yt-dlp` directement sur STYX :

```bash
pip install yt-dlp

# vampire — ambiance Nosferatu château gothique
yt-dlp --download-sections "*0:00-5:00" \
  -f "bestvideo[height<=720]+bestaudio/best[height<=720]" \
  --merge-output-format mp4 \
  -o "assets/video/vampire/vampire_placeholder.mp4" \
  "https://www.youtube.com/watch?v=OaedQzCtKgw"

# vampire — château Transylvanie nuit orageuse
yt-dlp --download-sections "*0:00-5:00" \
  -f "bestvideo[height<=720]+bestaudio/best[height<=720]" \
  --merge-output-format mp4 \
  -o "assets/video/vampire/transylvania_placeholder.mp4" \
  "https://www.youtube.com/watch?v=NdNg7KT8e_Q"
```

Ou via le script dédié :

```bash
bash scripts/download_placeholders.sh
```

## Sources placeholder par carte

| Carte     | Fichier cible                                | URL source                                      | Durée coupée |
|-----------|----------------------------------------------|-------------------------------------------------|--------------|
| vampire   | vampire/vampire_placeholder.mp4              | https://www.youtube.com/watch?v=OaedQzCtKgw     | 0:00 - 5:00  |
| vampire   | vampire/transylvania_placeholder.mp4         | https://www.youtube.com/watch?v=NdNg7KT8e_Q     | 0:00 - 5:00  |
| bougie    | bougie/bougie_placeholder.mp4                | _à définir_                                     | -            |
| cellule   | cellule/cellule_placeholder.mp4              | _à définir_                                     | -            |
| chaudron  | chaudron/chaudron_placeholder.mp4            | _à définir_                                     | -            |
| dague     | dague/dague_placeholder.mp4                  | _à définir_                                     | -            |

## Intégration player

Le player est géré dans `apps/video_player.py`.
La carte détectée déclenche automatiquement la vidéo correspondante via `pipeline.py`.
