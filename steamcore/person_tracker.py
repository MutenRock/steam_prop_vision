"""
steamcore/person_tracker.py
Gestion avancee du joueur :

  1. Timer de presence : active INSPECTION apres PERSON_DURATION secondes
  2. Persistance : reste actif PERSIST_AFTER_LOSS secondes apres disparition
  3. Comptage : nombre de personnes detectees dans la frame (YOLO boxes)
  4. Mouvement : vecteur de deplacement du joueur frame-a-frame (bbox centroid)
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum, auto


class PersonState(Enum):
    ABSENT     = auto()   # personne absente + persistance expiree
    PRESENT    = auto()   # personne vue
    PERSISTING = auto()   # personne disparue mais persistance encore active


@dataclass
class MovementVector:
    dx: float = 0.0   # pixels/frame, positif = droite
    dy: float = 0.0   # pixels/frame, positif = bas
    speed: float = 0.0  # magnitude

    @property
    def direction(self) -> str:
        if self.speed < 3:
            return "statique"
        angle_threshold = 0.5
        if abs(self.dx) > abs(self.dy):
            return "droite" if self.dx > 0 else "gauche"
        else:
            return "bas" if self.dy > 0 else "haut"


@dataclass
class PersonFrame:
    count: int                       # nb personnes dans la frame
    centroid: tuple[float, float] | None   # (x, y) du joueur principal
    bbox: tuple[int,int,int,int] | None    # (x1,y1,x2,y2) bbox principale


@dataclass
class PersonTrackerState:
    person_state:     PersonState
    person_count:     int
    ready_for_inspect: bool          # True si presence >= PERSON_DURATION
    movement:         MovementVector
    presence_elapsed: float          # secondes de presence continue
    persist_remaining: float         # secondes de persistance restantes


class PersonTracker:
    def __init__(
        self,
        person_duration: float  = 2.0,    # secondes avant INSPECTION
        persist_after_loss: float = 5.0,  # secondes de persistance apres disparition
        grace_frames: int       = 15,     # frames manquees tolerees
        movement_smoothing: int = 5,      # historique centroid pour moyenne mobile
    ):
        self.person_duration    = person_duration
        self.persist_after_loss = persist_after_loss
        self.grace_frames       = grace_frames
        self.movement_smoothing = movement_smoothing

        self._first_seen:  float = 0.0
        self._last_seen:   float = 0.0
        self._miss_count:  int   = 0
        self._persisting:  bool  = False
        self._persist_start: float = 0.0

        self._centroid_history: list[tuple[float, float]] = []
        self._prev_centroid: tuple[float, float] | None = None

    # ── API principale ────────────────────────────────────────────
    def update(self, frame_data: PersonFrame) -> PersonTrackerState:
        now = time.time()
        person_seen = frame_data.count > 0

        if person_seen:
            self._miss_count = 0
            self._persisting = False

            if self._first_seen == 0.0:
                self._first_seen = now
                print("[person] Joueur detecte, decompte...")

            self._last_seen = now
            self._update_movement(frame_data.centroid)

        else:
            self._miss_count += 1

            if self._miss_count >= self.grace_frames and self._first_seen > 0.0:
                if not self._persisting:
                    self._persisting   = True
                    self._persist_start = now
                    print("[person] Joueur perdu -> persistance " + str(self.persist_after_loss) + "s")

        # Expiration de la persistance
        if self._persisting:
            elapsed_persist = now - self._persist_start
            if elapsed_persist >= self.persist_after_loss:
                print("[person] Persistance expiree -> reset")
                self._reset()

        # Calcul etat
        if self._first_seen > 0.0 or self._persisting:
            state = PersonState.PERSISTING if self._persisting else PersonState.PRESENT
        else:
            state = PersonState.ABSENT

        presence_elapsed  = (now - self._first_seen) if self._first_seen > 0.0 else 0.0
        ready             = presence_elapsed >= self.person_duration and not self._persisting
        persist_remaining = max(0.0, self.persist_after_loss - (now - self._persist_start))                             if self._persisting else 0.0

        return PersonTrackerState(
            person_state      = state,
            person_count      = frame_data.count,
            ready_for_inspect  = ready,
            movement          = self._get_movement(),
            presence_elapsed  = presence_elapsed,
            persist_remaining = persist_remaining,
        )

    def reset(self):
        self._reset()

    # ── Interne ───────────────────────────────────────────────────
    def _reset(self):
        self._first_seen  = 0.0
        self._last_seen   = 0.0
        self._miss_count  = 0
        self._persisting  = False
        self._persist_start = 0.0
        self._centroid_history.clear()
        self._prev_centroid = None

    def _update_movement(self, centroid: tuple[float, float] | None):
        if centroid is None:
            return
        self._centroid_history.append(centroid)
        if len(self._centroid_history) > self.movement_smoothing:
            self._centroid_history.pop(0)

    def _get_movement(self) -> MovementVector:
        if len(self._centroid_history) < 2:
            return MovementVector()
        # Moyenne mobile sur les N derniers centroids
        c1 = self._centroid_history[0]
        c2 = self._centroid_history[-1]
        n  = max(len(self._centroid_history) - 1, 1)
        dx = (c2[0] - c1[0]) / n
        dy = (c2[1] - c1[1]) / n
        speed = (dx**2 + dy**2) ** 0.5
        return MovementVector(dx=dx, dy=dy, speed=speed)
