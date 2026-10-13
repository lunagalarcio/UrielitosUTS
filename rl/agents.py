"""Agentes RL sin dependencia de torch: REINFORCE (PPO-style) y DQN tabular/MLP.

Si stable-baselines3 + torch están disponibles, se usan de forma preferente
(ver `train_rl_sb3`); en caso contrario se usan estos agentes numpy/sklearn,
100% funcionales para la hackathon.
"""
from __future__ import annotations

import numpy as np
from sklearn.neural_network import MLPClassifier, MLPRegressor

from src.utils.helpers import get_logger

log = get_logger(__name__)


class PolicyGradientAgent:
    """REINFORCE con baseline y clipping estilo PPO (numpy puro)."""

    def __init__(self, obs_dim: int, lr: float = 0.05, hidden: int = 64, seed: int = 42) -> None:
        self.rng = np.random.default_rng(seed)
        self.W1 = self.rng.normal(0, 0.1, (obs_dim, hidden))
        self.b1 = np.zeros(hidden)
        self.W2 = self.rng.normal(0, 0.1, hidden)
        self.b2 = 0.0
        self.lr = lr
        self.baseline = 0.0

    def _forward(self, obs: np.ndarray) -> tuple[np.ndarray, float]:
        h = np.tanh(obs @ self.W1 + self.b1)
        logit = float(h @ self.W2 + self.b2)
        p = 1.0 / (1.0 + np.exp(-logit))
        return h, float(np.clip(p, 1e-4, 1 - 1e-4))

    def act(self, obs: np.ndarray, deterministic: bool = False) -> tuple[int, float]:
        _, p = self._forward(obs)
        if deterministic:
            return (1 if p >= 0.5 else 0), p
        return (1 if self.rng.random() < p else 0), p

    def update_episode(self, obs_list: list[np.ndarray], act_list: list[int],
                       rew_list: list[float], gamma: float = 0.99, clip: float = 0.2) -> float:
        G, returns = 0.0, []
        for r in reversed(rew_list):
            G = r + gamma * G
            returns.append(G)
        returns = np.array(returns[::-1])
        adv = returns - self.baseline
        self.baseline = 0.9 * self.baseline + 0.1 * float(returns.mean())
        std = adv.std() + 1e-8
        adv = adv / std
        total_loss = 0.0
        for obs, a, ad in zip(obs_list, act_list, adv):
            h, p = self._forward(obs)
            ratio_term = np.clip(ad, -clip, clip) if ad < 0 else ad
            grad_logit = (a - p) * ratio_term
            dh = grad_logit * self.W2 * (1 - h ** 2)
            self.W2 += self.lr * grad_logit * h
            self.b2 += self.lr * grad_logit
            self.W1 += self.lr * np.outer(obs, dh)
            self.b1 += self.lr * dh
            total_loss += float(-grad_logit)
        return total_loss / max(len(obs_list), 1)


class DQNAgent:
    """DQN con aproximador MLPRegressor (Q(s,0), Q(s,1)) y replay buffer."""

    def __init__(self, obs_dim: int, seed: int = 42) -> None:
        self.model = MLPRegressor(hidden_layer_sizes=(64, 32), activation="tanh",
                                  max_iter=1, warm_start=True, random_state=seed)
        self.buffer: list[tuple[np.ndarray, int, float, np.ndarray, bool]] = []
        self._init = False
        self.obs_dim = obs_dim

    def _q(self, obs: np.ndarray) -> np.ndarray:
        if not self._init:
            return np.zeros(2)
        X = np.array([np.concatenate([obs, [0.0]]), np.concatenate([obs, [1.0]])])
        return np.asarray(self.model.predict(X)).reshape(2)

    def act(self, obs: np.ndarray, epsilon: float = 0.0) -> int:
        if np.random.random() < epsilon or not self._init:
            return int(np.random.randint(2))
        return int(np.argmax(self._q(obs)))

    def remember(self, s: np.ndarray, a: int, r: float, s2: np.ndarray, done: bool) -> None:
        self.buffer.append((s, a, r, s2, done))
        if len(self.buffer) > 5000:
            self.buffer.pop(0)

    def replay(self, gamma: float = 0.95, batch: int = 64) -> float:
        if len(self.buffer) < batch:
            return 0.0
        idx = np.random.choice(len(self.buffer), batch, replace=False)
        X = np.array([np.concatenate([self.buffer[i][0], [self.buffer[i][1]]]) for i in idx])
        y = np.zeros(batch)
        for k, i in enumerate(idx):
            s, a, r, s2, done = self.buffer[i]
            target = r if done else r + gamma * np.max(self._q(s2))
            y[k] = target
        if not self._init:
            self.model.fit(X, y)
            self._init = True
        else:
            self.model.fit(X, y)
        pred = self.model.predict(X)
        return float(np.mean((pred - y) ** 2))

    def priority_score(self, obs: np.ndarray) -> float:
        q = self._q(obs)
        return float(q[1] - q[0])


class LogisticPrioridad:
    """Modelo interpretable de respaldo: P(priorizar|x) vía MLPClassifier."""

    def __init__(self) -> None:
        self.clf = MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=800, random_state=42)

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self.clf.fit(X, y)

    def proba(self, X: np.ndarray) -> np.ndarray:
        return self.clf.predict_proba(X)[:, 1]
