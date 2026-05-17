# Algorigramme — S.T.E.A.M Vision

Fonctionnement complet du système, de l'acquisition caméra au déclenchement des effets.

---

## Pipeline principale

```mermaid
flowchart TD
    A([🟢 Démarrage]) --> B[Initialisation\nPicamera2 · YOLO · SIFT · ORB · UDP · WebSocket]
    B --> C[/Lecture frame\nIMX708/]
    C --> D{Mode\ncard_first ?}

    D -- OUI --> E[🔍 L1 — FastDetector\nScan losange dans la frame]
    D -- NON --> F[👤 YOLO — Détection joueur]

    E --> G{Losange\ndétecté ?}
    G -- NON --> C
    G -- OUI --> H[👤 YOLO — Vérif présence joueur]

    F --> I{Joueur\nprésent ?}
    I -- NON --> C
    I -- OUI --> J[⏱️ PersonTracker\nprésence >= 2s ?]
    J -- NON --> C
    J -- OUI --> E

    H --> K{Joueur\nprésent ?}
    K -- NON --> C
    K -- OUI --> L

    L[🔎 L2 — CardDetector\nSIFT + BFMatcher + homographie RANSAC\nWarp 400×400 normalisé]
    L --> M{Warp\nvalide ?}
    M -- NON --> C
    M -- OUI --> N[🧠 L3 — CardRecognizer\nORB matching sur warp\ncomparaison vs templates PLATEST]
    N --> O{Score ORB\n>= seuil ?}
    O -- NON --> C
    O -- OUI --> P[✅ Carte identifiée\ncard_id · label · score]

    P --> Q[📋 Lookup rules.yaml\nRecherche règles pour cette carte]
    Q --> R[🚀 Exécution actions]

    R --> S[📡 UDP → Loxone\nSTEAM_CARD_xxx]
    R --> T[🎬 VideoPlayer mpv\nlecture vidéo plein écran]
    R --> U[🔊 Audio\nlecture son associé]
    R --> V[📺 WebSocket Monitor\névénement card_detected]

    S & T & U & V --> W[⏳ Cooldown\ncard_cooldown secondes]
    W --> C
```

---

## Machine à états

```mermaid
stateDiagram-v2
    [*] --> IDLE : Démarrage

    IDLE --> IDLE : Aucun joueur / Aucune carte
    IDLE --> INSPECTION : Joueur présent >= 2s\n(mode legacy)
    IDLE --> TRIGGERED : Losange détecté + joueur présent\n(mode card_first)

    INSPECTION --> IDLE : Timeout (15s)\nou joueur absent > 5s
    INSPECTION --> TRIGGERED : Carte reconnue\n(score >= seuil)

    TRIGGERED --> IDLE : Cooldown écoulé\n(card_cooldown)

    note right of IDLE : Idle screen affiché\nTexte configurable
    note right of TRIGGERED : UDP · Vidéo · Audio\nOSD nom de carte
```

---

## Détail détection carte (L2 → L3)

```mermaid
flowchart LR
    subgraph L2 [L2 — CardDetector SIFT]
        A2[Frame caméra] --> B2[Extraction keypoints SIFT\nsur toute la frame]
        B2 --> C2[BFMatcher vs templates PLATEST]
        C2 --> D2{≥ card_min_matches\npoints correspondants ?}
        D2 -- OUI --> E2[Homographie RANSAC\n4 coins → warp]
        E2 --> F2[Patch normalisé\n400×400 px]
    end

    subgraph L3 [L3 — CardRecognizer ORB]
        F2 --> G3[ORB matching\nwarp vs quadrants\ntop / bottom / left / right]
        G3 --> H3[Score moyen\npar template]
        H3 --> I3{Score\n>= threshold ?}
        I3 -- OUI --> J3[Card identifiée ✅\ncard_id · score · matches]
        I3 -- NON --> K3[Rejeté ❌]
    end
```

---

## Communication réseau

```mermaid
flowchart LR
    STYX["🖥️ STYX\n(Raspberry Pi 5)"]

    STYX -->|UDP port 8888\nSTEAM_CARD_xxx| LOX[🏠 Loxone\nBox domotique]
    STYX -->|UDP Heartbeat\nSTEAM_RUN_OK toutes 5s| LOX
    LOX -->|UDP commandes retour\nport 8888| STYX

    STYX -->|WebSocket\nws://STYX:8889| MON[📊 Monitor\nNavigateur / Dashboard]

    STYX -->|mpv IPC socket| VID[🎬 VideoPlayer\nPlein écran HDMI]
```

---

## Ajout d'une nouvelle plate

```mermaid
flowchart TD
    S([Nouvelle plaque physique]) --> P[📸 Photographier la plaque\n10-15 photos, angles variés]
    P --> CP[Copier dans\nPLATEST/plate_xxx/]
    CP --> SPLIT[Lancer split_plate.py\nou add_plate.sh]
    SPLIT --> QUADS[Génération quadrants\ntop / bottom / left / right]
    QUADS --> AUG[Augmentation\ngenerate_samples.py --count 15]
    AUG --> BENCH[Validation bench\nplate_bench.py --pi]
    BENCH --> OK{Score\nsatisfaisant ?}
    OK -- NON --> P
    OK -- OUI --> CFG[Ajouter dans\nrules.yaml + gui_setup.py]
    CFG --> PROD([✅ Plate opérationnelle])
```
