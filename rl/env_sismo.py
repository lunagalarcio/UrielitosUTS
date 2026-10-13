"""Entorno Gymnasium para priorización de municipios."""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import gymnasium as gym
    from gymnasium import spaces

    _HAS_GYM = True
except ImportError:  # fallback mínimo si gymnasium no está instalado
    _HAS_GYM = False

    class _Dummy:  # type: ignore[no-redef]
        pass

    gym = _Dummy()  # type: ignore[assignment]
    spaces = _Dummy()  # type: ignore[assignment]


class SismoPrioridadEnv(gym.Env if _HAS_GYM else object):
    """Un episodio = recorrer todos los municipios en orden aleatorio.

    Estado: vector de features normalizadas del municipio actual (+ contexto).
    Acciones: 0 = no priorizar, 1 = priorizar.
    Recompensa: proporcional al riesgo real del municipio.

    R(a=1) = +2*r - 1 + bonus_exposicion ; R(a=0) = +0.3*(1-r) - 0.7*r
    donde r = indice_riesgo en [0,1]. Priorizar un municipio de alto riesgo
    da recompensa alta; priorizar uno de bajo riesgo la da negativa.
    """

    metadata = {"render_modes": []}

    def __init__(self, features: pd.DataFrame, seed: int = 42) -> None:
        super().__init__()
        self.df = features.reset_index(drop=True)
        self.rng = np.random.default_rng(seed)
        self.cols = [c for c in self.df.columns if c not in ("cod_mpio", "municipio")]
        X = self.df[self.cols].fillna(0).to_numpy(dtype=float)
        self.mu = X.mean(axis=0)
        self.sd = X.std(axis=0) + 1e-8
        self.Xn = (X - self.mu) / self.sd
        self.risk = self.df["indice_riesgo"].to_numpy(dtype=float) if "indice_riesgo" in self.df else np.zeros(len(self.df))
        self.expo = self.df["indice_exposicion"].to_numpy(dtype=float) if "indice_exposicion" in self.df else np.zeros(len(self.df))
        self.order: np.ndarray = np.arange(len(self.df))
        self.pos = 0
        self.n = len(self.df)
        if _HAS_GYM:
            self.observation_space = spaces.Box(low=-10, high=10, shape=(len(self.cols) + 2,), dtype=np.float32)
            self.action_space = spaces.Discrete(2)

    # -- API gymnasium -----------------------------------------------------
    def reset(self, *, seed: int | None = None, options: dict | None = None):  # type: ignore[override]
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.order = self.rng.permutation(self.n)
        self.pos = 0
        obs = self._obs()
        if _HAS_GYM:
            return obs, {}
        return obs

    def _obs(self) -> np.ndarray:
        i = self.order[self.pos] if self.pos < self.n else self.order[-1]
        frac = self.pos / max(self.n, 1)
        return np.concatenate([self.Xn[i].astype(np.float32), np.array([frac, 1 - frac], dtype=np.float32)])

    def step(self, action: int):  # type: ignore[override]
        i = self.order[self.pos]
        r = float(self.risk[i])
        e = float(self.expo[i])
        action = int(action)
        if action == 1:
            reward = (2.0 * r - 1.0) + 0.5 * e * r
        else:
            reward = 0.3 * (1.0 - r) - 0.7 * r
        self.pos += 1
        terminated = self.pos >= self.n
        obs = self._obs()
        if _HAS_GYM:
            return obs, float(reward), terminated, False, {"mpio_idx": int(i)}
        return obs, float(reward), terminated, {"mpio_idx": int(i)}

    # -- Utilidades ----------------------------------------------------------
    def score_action(self, muni_row_idx: int, action: int) -> float:
        """Recompensa inmediata teórica (para análisis)."""
        r, e = float(self.risk[muni_row_idx]), float(self.expo[muni_row_idx])
        if int(action) == 1:
            return (2.0 * r - 1.0) + 0.5 * e * r
        return 0.3 * (1.0 - r) - 0.7 * r
