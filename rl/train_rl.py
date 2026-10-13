"""Entrenamiento RL: PPO-style (PolicyGradient) vs DQN. Selecciona el mejor por recompensa media."""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd

from src import config
from rl.agents import DQNAgent, PolicyGradientAgent
from rl.env_sismo import SismoPrioridadEnv
from src.utils.helpers import get_logger, save_json

log = get_logger(__name__)


def _run_episode(env: SismoPrioridadEnv, agent, algo: str, epsilon: float = 0.0,
                 train: bool = True, gamma: float = 0.99) -> float:
    obs = env.reset()
    if isinstance(obs, tuple):  # gymnasium devuelve (obs, info)
        obs = obs[0]
    obs_l, act_l, rew_l = [], [], []
    total = 0.0
    done = False
    while not done:
        if algo == "ppo":
            a, _ = agent.act(np.asarray(obs, dtype=float))
        else:
            a = agent.act(np.asarray(obs, dtype=float), epsilon=epsilon)
        out = env.step(a)
        if len(out) == 5:
            obs2, r, term, trunc, _ = out
            done = bool(term or trunc)
        else:
            obs2, r, done, _ = out
        total += r
        if algo == "ppo":
            obs_l.append(np.asarray(obs, dtype=float)); act_l.append(a); rew_l.append(r)
        else:
            agent.remember(np.asarray(obs, dtype=float), a, r, np.asarray(obs2, dtype=float), done)
            if train:
                agent.replay(gamma=gamma)
        obs = obs2
    if algo == "ppo" and train:
        agent.update_episode(obs_l, act_l, rew_l, gamma=gamma)
    return total


def _sb3_train(env_fn, algo: str, steps: int = 8000) -> tuple[object, float] | None:
    """Intenta entrenar con stable-baselines3 si está instalado."""
    try:
        import importlib

        sb3 = importlib.import_module("stable_baselines3")
        Algo = sb3.PPO if algo == "ppo" else sb3.DQN
        model = Algo("MlpPolicy", env_fn(), verbose=0)
        model.learn(total_timesteps=steps)
        # Evaluación
        rews = []
        for _ in range(5):
            env = env_fn()
            obs, _ = env.reset()
            done, tot = False, 0.0
            while not done:
                a, _ = model.predict(obs, deterministic=True)
                obs, r, term, trunc, _ = env.step(int(a))
                tot += r
                done = bool(term or trunc)
            rews.append(tot)
        return model, float(np.mean(rews))
    except Exception as exc:
        log.warning("SB3 no disponible para %s (%s); usando agente propio", algo, exc)
        return None


def train_rl(features: pd.DataFrame | None = None, episodes: int = 120) -> dict:
    """Entrena PPO-style y DQN, evalúa y guarda el mejor agente + ranking.

    Returns:
        Diccionario con recompensas comparadas y agente ganador.
    """
    features = features if features is not None else pd.read_csv(config.FEATURES)
    env_fn = lambda seed=42: SismoPrioridadEnv(features, seed=seed)
    probe = env_fn()
    obs_dim = probe._obs().shape[0]

    results: dict[str, float] = {}
    trained: dict[str, object] = {}

    # 1) Intentar SB3
    for algo in ["ppo", "dqn"]:
        sb3 = _sb3_train(env_fn, algo)
        if sb3 is not None:
            trained[algo], results[algo.upper()] = sb3

    # 2) Agentes propios (siempre se entrenan como respaldo/comparación)
    curvas: dict[str, list[float]] = {"ppo": [], "dqn": []}
    ppo = PolicyGradientAgent(obs_dim)
    for ep in range(episodes):
        curvas["ppo"].append(_run_episode(env_fn(seed=1000 + ep), ppo, "ppo"))
    dqn = DQNAgent(obs_dim + 1)  # estado + acción como entrada del MLP
    for ep in range(episodes):
        eps = max(0.05, 1.0 - ep / (episodes * 0.8))
        curvas["dqn"].append(_run_episode(env_fn(seed=2000 + ep), dqn, "dqn", epsilon=eps))
    pd.DataFrame([{"epoca": i + 1, "algoritmo": a, "recompensa": r}
                  for a, rs in curvas.items() for i, r in enumerate(rs)]).to_csv(
        config.DATA_PROC / "curva_rl.csv", index=False)

    def _eval(agent, algo: str, n: int = 10) -> float:
        tots = [_run_episode(env_fn(seed=9000 + k), agent, algo, epsilon=0.0, train=False) for k in range(n)]
        return float(np.mean(tots))

    results.setdefault("PPO", _eval(ppo, "ppo"))
    results.setdefault("DQN", _eval(dqn, "dqn"))
    log.info("Recompensas medias: %s", {k: round(v, 2) for k, v in results.items()})

    winner = max(results, key=results.get)
    log.info("Agente ganador: %s (%.2f)", winner, results[winner])

    # Ranking: puntuación de priorización por municipio
    env = env_fn(seed=7)
    scores: list[float] = []
    for i in range(env.n):
        obs = np.concatenate([env.Xn[i].astype(np.float32), np.array([0.0, 1.0], dtype=np.float32)])
        if winner == "PPO" and "ppo" in trained and hasattr(trained["ppo"], "predict"):
            p, _ = trained["ppo"].predict(obs, deterministic=True)
            score = float(p)
        elif winner == "DQN" and "dqn" in trained and hasattr(trained["dqn"], "predict"):
            q = trained["dqn"].predict(obs, deterministic=True)[0]
            score = float(q)
        elif winner == "PPO":
            _, score = ppo.act(obs, deterministic=False)
        else:
            score = dqn.priority_score(obs) if dqn._init else float(env.risk[i])
        scores.append(score)
    ranking = pd.DataFrame({"cod_mpio": env.df["cod_mpio"], "municipio": env.df["municipio"],
                            "indice_riesgo": env.risk, "score_rl": scores})
    # Normalizar score a 0-100 y ordenar
    lo, hi = ranking["score_rl"].min(), ranking["score_rl"].max()
    ranking["score_rl_100"] = ((ranking["score_rl"] - lo) / (hi - lo + 1e-9) * 100).round(2)
    ranking = ranking.sort_values("score_rl_100", ascending=False).reset_index(drop=True)
    ranking["puesto"] = ranking.index + 1
    ranking.to_csv(config.RANKING_RL, index=False)

    meta = {"ganador": winner, "recompensas_medias": {k: round(float(v), 3) for k, v in results.items()},
            "episodios": episodes, "n_municipios": int(env.n)}
    save_json(meta, config.RL_META)
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"algo": winner, "ppo": None if winner != "PPO" or "ppo" in trained else
                 {"W1": ppo.W1, "b1": ppo.b1, "W2": ppo.W2, "b2": ppo.b2},
                 "risk": env.risk, "scores": np.array(scores)}, config.RL_MODEL)
    for k, v in trained.items():  # guardar modelos SB3 si existen
        try:
            v.save(str(config.MODELS_DIR / f"rl_{k}_sb3"))
        except Exception:
            pass
    return meta
