"""논문용 그림 4, 5 생성 — matplotlib 차트.

그림 4: Judge 메트릭별 MAE–τ 산점도 (GPT-4o-mini vs Gemini 3.1 Pro)
그림 5: Position Bias 점수 차이 분포 (Citation Accuracy)

출력: docs/figures/fig4_judge_scatter.png, docs/figures/fig5_position_bias.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

matplotlib.rcParams["font.family"] = ["AppleGothic", "Malgun Gothic", "NanumGothic", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False

OUT_DIR = Path("docs/figures")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DPI = 300


def fig4_judge_scatter() -> Path:
    """그림 4: Judge 메트릭별 MAE–Kendall τ 산점도.

    좌상단(MAE 낮고 τ 높음) 근접 = 높은 일치도.
    데이터 출처: docs/experiment-results.md §5.2
    """
    metrics = {
        "Citation\nAccuracy": {"tau": 0.2712, "mae": 0.4045, "class_agr": 88.76},
        "Completeness": {"tau": 0.2299, "mae": 0.4719, "class_agr": 87.27},
        "Readability": {"tau": 0.3953, "mae": 0.0431, "class_agr": 98.50},
        "Average": {"tau": 0.2591, "mae": 0.3066, "class_agr": 90.26},
    }

    fig, ax = plt.subplots(figsize=(7, 5.5))

    colors = ["#e74c3c", "#e67e22", "#2ecc71", "#3498db"]
    markers = ["o", "s", "D", "^"]

    for i, (name, vals) in enumerate(metrics.items()):
        ax.scatter(
            vals["mae"],
            vals["tau"],
            s=vals["class_agr"] * 3,
            c=colors[i],
            marker=markers[i],
            edgecolors="white",
            linewidths=1.5,
            zorder=5,
            label=f"{name} (Class Agr. {vals['class_agr']:.1f}%)",
        )
        ax.annotate(
            name,
            (vals["mae"], vals["tau"]),
            textcoords="offset points",
            xytext=(12, 8) if name != "Average" else (12, -12),
            fontsize=10,
            fontweight="bold",
            color=colors[i],
        )

    ax.set_xlabel("MAE (Mean Absolute Error)", fontsize=12, fontweight="bold")
    ax.set_ylabel("Kendall τ (순위 상관)", fontsize=12, fontweight="bold")
    ax.set_title(
        "GPT-4o-mini vs Gemini 3.1 Pro Judge\n메트릭별 일치도 (N=267)",
        fontsize=14,
        fontweight="bold",
        pad=12,
    )

    ax.set_xlim(-0.02, 0.55)
    ax.set_ylim(0.18, 0.45)

    ax.axhspan(0.35, 0.45, xmin=0, xmax=0.2, alpha=0.08, color="green", zorder=0)
    ax.annotate(
        "높은 일치도\n(좌상단)",
        xy=(0.02, 0.43),
        fontsize=9,
        fontstyle="italic",
        color="#27ae60",
        alpha=0.7,
    )

    ax.legend(
        loc="lower right",
        fontsize=9,
        framealpha=0.9,
        edgecolor="#ccc",
        title="메트릭 (버블 크기 = Class Agreement)",
        title_fontsize=9,
    )
    ax.grid(True, alpha=0.3, linestyle="--")

    ax.text(
        0.98,
        0.02,
        "Class Agreement 전체: 90.3%",
        transform=ax.transAxes,
        fontsize=9,
        ha="right",
        va="bottom",
        fontstyle="italic",
        color="#555",
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "#f0f0f0", "edgecolor": "#ccc"},
    )

    fig.tight_layout()
    path = OUT_DIR / "fig4_judge_scatter.png"
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"그림 4 저장: {path}")
    return path


def fig5_position_bias() -> Path:
    """그림 5: Position Bias 점수 차이 분포 (Citation Accuracy).

    원본 순서 vs 셔플 순서 간 절대 점수 차이 분포.
    데이터 출처: docs/experiment-results.md §6.1
    """
    fig, axes = plt.subplots(1, 3, figsize=(14, 5), sharey=True)

    data = {
        "Citation Accuracy": {
            "deltas": [0, 2, 4],
            "counts": [429, 22, 8],
            "total": 459,
            "color": "#e74c3c",
            "ge1_pct": 6.5,
            "max_delta": 4,
            "wilcoxon_p": 0.618,
        },
        "Completeness": {
            "deltas": [0, 1, 2],
            "counts": [440, 5, 14],
            "total": 459,
            "color": "#e67e22",
            "ge1_pct": 4.1,
            "max_delta": 2,
            "wilcoxon_p": 0.849,
        },
        "Readability": {
            "deltas": [0, 1, 2],
            "counts": [451, 3, 5],
            "total": 459,
            "color": "#2ecc71",
            "ge1_pct": 1.7,
            "max_delta": 2,
            "wilcoxon_p": 1.000,
        },
    }

    for ax, (name, d) in zip(axes, data.items()):
        total = d["total"]
        pcts = [c / total * 100 for c in d["counts"]]

        bars = ax.bar(
            [str(x) for x in d["deltas"]],
            pcts,
            color=d["color"],
            alpha=0.8,
            edgecolor="white",
            linewidth=1.5,
            width=0.6,
        )

        for bar, pct, cnt in zip(bars, pcts, d["counts"]):
            if pct > 3:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 1.5,
                    f"{pct:.1f}%\n({cnt}건)",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    fontweight="bold",
                )
            else:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 1.5,
                    f"{pct:.1f}%\n({cnt}건)",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    color="#666",
                )

        ax.set_title(name, fontsize=13, fontweight="bold", color=d["color"], pad=10)
        ax.set_xlabel("|Δ score| (원본 - 셔플)", fontsize=11)

        info_text = f"≥1점 차이: {d['ge1_pct']}%\n최대 차이: {d['max_delta']}점\nWilcoxon p={d['wilcoxon_p']:.3f}"
        ax.text(
            0.97,
            0.97,
            info_text,
            transform=ax.transAxes,
            fontsize=9,
            ha="right",
            va="top",
            bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "edgecolor": "#ccc", "alpha": 0.9},
        )

        ax.grid(True, axis="y", alpha=0.3, linestyle="--")
        ax.set_ylim(0, 110)

    axes[0].set_ylabel("비율 (%)", fontsize=12, fontweight="bold")

    fig.suptitle(
        "Position Bias 점수 차이 분포 (N=459, GPT-4o-mini Judge)",
        fontsize=14,
        fontweight="bold",
        y=1.02,
    )

    fig.text(
        0.5,
        -0.02,
        "모든 차원에서 Wilcoxon p > 0.05 → 체계적 편향 없음. 2회 평균 분산 감소: 2.79%",
        ha="center",
        fontsize=10,
        fontstyle="italic",
        color="#555",
    )

    fig.tight_layout()
    path = OUT_DIR / "fig5_position_bias.png"
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"그림 5 저장: {path}")
    return path


if __name__ == "__main__":
    fig4_judge_scatter()
    fig5_position_bias()
    print("완료!")
