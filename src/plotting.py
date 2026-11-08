import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, NullFormatter, PercentFormatter
from matplotlib.transforms import blended_transform_factory

from src.analysis import METRICS_PATH, OUTPUT_DIR, lorenz_curve, load_metrics
from src.warehouse import connect_read_only

FIGURE_DPI: int = 300
FIGURE_FILENAMES: tuple[str, ...] = (
    "01_cohort_retention_heatmap.png",
    "02_sla_breach_penalty_curve.png",
    "03_seller_pareto_lorenz.png",
    "04_logit_odds_ratios_forest.png",
)

SURFACE: str = "#fcfcfb"
INK_PRIMARY: str = "#0b0b0b"
INK_SECONDARY: str = "#52514e"
INK_MUTED: str = "#898781"
GRID_COLOR: str = "#e1e0d9"
AXIS_COLOR: str = "#c3c2b7"
ON_TIME_COLOR: str = "#2a78d6"
BREACH_COLOR: str = "#eb6834"
TIER_COLORS: tuple[str, ...] = ("#104281", "#2a78d6", "#86b6ef")
SEQUENTIAL_STEPS: tuple[str, ...] = ("#f3f8fe", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")
CONFIDENCE_BAND_ALPHA: float = 0.14

PROVENANCE_NOTE: str = (
    "Source: Olist Brazilian E-Commerce Public Dataset (github.com/olist/work-at-olist-data), "
    "delivered orders purchased Sep 2016 – Aug 2018. Pipeline: DuckDB SQL marts + scipy/statsmodels. "
    "Reproduce with `python run.py`."
)

HOUSE_STYLE: dict[str, Any] = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial", "Liberation Sans"],
    "font.size": 9,
    "axes.titlesize": 10.5,
    "axes.titleweight": "semibold",
    "axes.titlecolor": INK_PRIMARY,
    "axes.titlelocation": "left",
    "axes.titlepad": 10,
    "axes.labelsize": 9,
    "axes.labelcolor": INK_SECONDARY,
    "axes.edgecolor": AXIS_COLOR,
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.facecolor": SURFACE,
    "axes.grid": False,
    "axes.axisbelow": True,
    "grid.color": GRID_COLOR,
    "grid.linewidth": 0.6,
    "grid.linestyle": "-",
    "xtick.color": AXIS_COLOR,
    "ytick.color": AXIS_COLOR,
    "xtick.labelcolor": INK_SECONDARY,
    "ytick.labelcolor": INK_SECONDARY,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.frameon": False,
    "legend.fontsize": 8.5,
    "figure.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
}

SLA_BUCKET_LABELS: dict[str, str] = {
    "1. >7d Early": ">7d early",
    "2. 1-7d Early": "1–7d early",
    "3. On Time (Day 0)": "On time (Day 0)",
    "4. 1-3d Late": "1–3d late",
    "5. 4-7d Late": "4–7d late",
    "6. >7d Late": ">7d late",
}
TIER_LABELS: dict[str, str] = {
    "Top 10% Sellers": "Top 10%",
    "Middle 40% Sellers": "Middle 40%",
    "Bottom 50% Long-Tail": "Bottom 50%\nlong tail",
}
FEATURE_LABELS: dict[str, str] = {
    "is_sla_breached": "SLA breached\n(delivered after promised date)",
    "is_severe_detractor": "Severe detractor review\non first order",
    "log_order_gmv": "Order GMV, log(1 + BRL)\nper e-fold (≈2.7×) increase",
    "freight_ratio": "Freight share of order GMV\n0% → 100%",
    "log_distance_km": "Seller→customer distance,\nlog(1 + km), per e-fold",
}


def add_figure_header(figure: Figure, title: str, subtitle: str, left: float, top: float) -> None:
    figure.text(left, top, title, fontsize=14, fontweight="semibold", color=INK_PRIMARY, ha="left", va="bottom")
    figure.text(left, top - 0.012, subtitle, fontsize=9.5, color=INK_SECONDARY, ha="left", va="top")


def add_provenance_note(figure: Figure, extra_note: str, left: float, bottom: float) -> None:
    note = f"{extra_note}\n{PROVENANCE_NOTE}" if extra_note else PROVENANCE_NOTE
    figure.text(left, bottom, note, fontsize=7.5, color=INK_MUTED, ha="left", va="top", linespacing=1.5)


def save_figure(figure: Figure, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=FIGURE_DPI, bbox_inches="tight", pad_inches=0.25, facecolor=SURFACE)
    plt.close(figure)
    return output_path


def signed_number(value: float, decimals: int) -> str:
    return f"{value:+.{decimals}f}".replace("-", "−")


def format_p_value(p_value: float) -> str:
    return "p < 0.0001" if p_value < 1e-4 else f"p = {p_value:.4f}"


def sequential_colormap() -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list("olist_sequential_blue", list(SEQUENTIAL_STEPS))


def readable_ink_for_fill(normalised_value: float) -> str:
    return "#ffffff" if normalised_value >= 0.55 else INK_PRIMARY


def load_cohort_frame() -> pd.DataFrame:
    with connect_read_only() as connection:
        cohorts = connection.execute(
            """
            SELECT cohort_month, period_number, cohort_size, active_buyers, retention_rate_pct
            FROM mart_cohort_retention
            ORDER BY cohort_month, period_number
            """
        ).df()
    cohorts["cohort_month"] = pd.to_datetime(cohorts["cohort_month"])
    return cohorts


def annotate_heatmap_cells(axes: Axes, values: np.ma.MaskedArray, norm: Normalize, row_offset: float = 0.5) -> None:
    row_count, column_count = values.shape
    for row_index in range(row_count):
        for column_index in range(column_count):
            if values.mask[row_index, column_index]:
                continue
            cell_value = float(values[row_index, column_index])
            axes.text(
                column_index + 1,
                row_index + row_offset,
                f"{cell_value:.2f}%",
                ha="center",
                va="center",
                fontsize=7,
                color=readable_ink_for_fill(float(norm(cell_value))),
            )


def plot_cohort_retention_heatmap(output_path: Path) -> Path:
    cohorts = load_cohort_frame()
    retention_matrix = cohorts.pivot(index="cohort_month", columns="period_number", values="retention_rate_pct").reindex(
        columns=range(0, 12)
    )
    cohort_sizes = cohorts.loc[cohorts["period_number"] == 0].set_index("cohort_month")["cohort_size"]
    retained = cohorts.loc[cohorts["period_number"] >= 1]
    pooled_by_period = (
        retained.groupby("period_number")[["active_buyers", "cohort_size"]].sum().reindex(range(1, 12))
    )
    pooled_retention = (100.0 * pooled_by_period["active_buyers"] / pooled_by_period["cohort_size"]).to_numpy()
    retention_values = np.ma.masked_invalid(retention_matrix.loc[:, 1:11].to_numpy(dtype=float))
    pooled_values = np.ma.masked_invalid(pooled_retention.reshape(1, -1))
    scale_max = math.ceil(float(retention_values.max()) * 10.0) / 10.0
    norm = Normalize(vmin=0.0, vmax=scale_max)
    colormap = sequential_colormap()
    x_edges = np.arange(0.5, 12.5, 1.0)

    with plt.rc_context(HOUSE_STYLE):
        figure = plt.figure(figsize=(12.5, 10.5))
        grid = figure.add_gridspec(
            2, 2, height_ratios=[len(cohort_sizes), 1.15], width_ratios=[1.0, 0.022],
            hspace=0.06, wspace=0.025, left=0.17, right=0.93, top=0.90, bottom=0.08,
        )
        heatmap_axes = figure.add_subplot(grid[0, 0])
        pooled_axes = figure.add_subplot(grid[1, 0], sharex=heatmap_axes)
        colorbar_axes = figure.add_subplot(grid[0, 1])

        mesh = heatmap_axes.pcolormesh(
            x_edges, np.arange(len(cohort_sizes) + 1), retention_values,
            cmap=colormap, norm=norm, edgecolors=SURFACE, linewidth=1.6,
        )
        heatmap_axes.set_ylim(len(cohort_sizes), 0)
        annotate_heatmap_cells(heatmap_axes, retention_values, norm)
        heatmap_axes.set_yticks(
            np.arange(len(cohort_sizes)) + 0.5,
            labels=[f"{month:%Y-%m}   (n = {size:,})" for month, size in cohort_sizes.items()],
        )
        heatmap_axes.set_ylabel("Acquisition cohort (month of first delivered order)")
        heatmap_axes.tick_params(axis="x", labelbottom=False, length=0)
        heatmap_axes.tick_params(axis="y", length=0)

        pooled_axes.pcolormesh(x_edges, [0, 1], pooled_values, cmap=colormap, norm=norm, edgecolors=SURFACE, linewidth=1.6)
        pooled_axes.set_ylim(1, 0)
        annotate_heatmap_cells(pooled_axes, pooled_values, norm)
        pooled_axes.set_yticks([0.5], labels=["All cohorts (pooled)"])
        pooled_axes.set_xticks(range(1, 12), labels=[f"M{period}" for period in range(1, 12)])
        pooled_axes.set_xlabel("Months since first purchase (period number; period 0 = 100% by construction, excluded from scale)")
        pooled_axes.tick_params(length=0)
        for axes in (heatmap_axes, pooled_axes):
            for spine in axes.spines.values():
                spine.set_visible(False)

        colorbar = figure.colorbar(mesh, cax=colorbar_axes, format=PercentFormatter(xmax=100.0, decimals=1))
        colorbar.set_label("Active buyers / cohort size", color=INK_SECONDARY)
        colorbar.outline.set_visible(False)
        colorbar.ax.tick_params(color=AXIS_COLOR, labelcolor=INK_SECONDARY, length=2)

        peak_value = float(retention_values.max())
        add_figure_header(
            figure,
            "After the first order, monthly cohort retention never exceeds 1%",
            f"Share of each 2017-01 … 2018-08 acquisition cohort placing another delivered order k months later. "
            f"Peak cell = {peak_value:.2f}%; blank cells are not yet observable (right-censored at 2018-08).",
            left=0.02,
            top=0.935,
        )
        add_provenance_note(
            figure,
            "Customers resolved on customer_unique_id; cohorts anchored on the true first delivered order. "
            "~97% of customers buy exactly once, so near-zero cells are a finding, not a bug.",
            left=0.02,
            bottom=0.035,
        )
        return save_figure(figure, output_path)


def day_profile_frame(metrics: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "delay_day": row["sla_delay_days"],
                "orders": row["orders"],
                "mean_review": row["review_score"]["mean"],
                "review_ci_low": row["review_score"]["ci_low"],
                "review_ci_high": row["review_score"]["ci_high"],
                "detractor_rate": row["severe_detractor"]["rate_pct"],
                "detractor_ci_low": row["severe_detractor"]["ci_low_pct"],
                "detractor_ci_high": row["severe_detractor"]["ci_high_pct"],
            }
            for row in metrics["sla_delay_day_profile"]
        ]
    )


def bucket_profile_frame(metrics: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "bucket": row["sla_delay_bucket"],
                "orders": row["orders"],
                "mean_review": row["review_score"]["mean"],
                "review_ci_low": row["review_score"]["ci_low"],
                "review_ci_high": row["review_score"]["ci_high"],
                "detractor_rate": row["severe_detractor"]["rate_pct"],
                "detractor_ci_low": row["severe_detractor"]["ci_low_pct"],
                "detractor_ci_high": row["severe_detractor"]["ci_high_pct"],
            }
            for row in metrics["sla_bucket_profile"]
        ]
    )


def plot_day_series(axes: Axes, profile: pd.DataFrame, value_column: str, low_column: str, high_column: str) -> None:
    on_time_days = profile.loc[profile["delay_day"] <= 0]
    late_days = profile.loc[profile["delay_day"] >= 1]
    for segment, color in ((on_time_days, ON_TIME_COLOR), (late_days, BREACH_COLOR)):
        axes.fill_between(
            segment["delay_day"], segment[low_column], segment[high_column],
            color=color, alpha=CONFIDENCE_BAND_ALPHA, linewidth=0,
        )
        axes.plot(
            segment["delay_day"], segment[value_column], color=color, linewidth=1.8,
            marker="o", markersize=4.5, markeredgecolor=SURFACE, markeredgewidth=1.0, solid_capstyle="round",
        )
    day_zero = profile.loc[profile["delay_day"] == 0, value_column].iloc[0]
    day_one = profile.loc[profile["delay_day"] == 1, value_column].iloc[0]
    axes.plot([0, 1], [day_zero, day_one], color=INK_MUTED, linewidth=1.0, zorder=1)
    axes.axvline(0, color=INK_SECONDARY, linewidth=0.9, linestyle=(0, (4, 3)), zorder=0)
    axes.grid(axis="y")


def plot_bucket_bars(
    axes: Axes, buckets: pd.DataFrame, value_column: str, low_column: str, high_column: str, value_format: str
) -> None:
    positions = np.arange(len(buckets))
    colors = [ON_TIME_COLOR if index < 3 else BREACH_COLOR for index in range(len(buckets))]
    values = buckets[value_column].to_numpy()
    error_bars = np.vstack([values - buckets[low_column].to_numpy(), buckets[high_column].to_numpy() - values])
    axes.bar(
        positions, values, width=0.56, color=colors, yerr=error_bars,
        error_kw={"ecolor": INK_SECONDARY, "elinewidth": 0.9, "capsize": 2.5, "capthick": 0.9},
    )
    label_padding = 0.015 * axes.get_ylim()[1]
    for position, value, upper in zip(positions, values, buckets[high_column].to_numpy()):
        axes.text(position, upper + label_padding, value_format.format(value), ha="center", va="bottom", fontsize=8.5, color=INK_PRIMARY)
    axes.grid(axis="y")


def plot_sla_breach_penalty_curve(metrics: dict[str, Any], output_path: Path) -> Path:
    days = day_profile_frame(metrics)
    buckets = bucket_profile_frame(metrics)
    discontinuity = metrics["sla_threshold_discontinuity"]
    review_test = metrics["two_sample_tests"]["review_score"]
    day_zero = days.loc[days["delay_day"] == 0].iloc[0]
    day_one = days.loc[days["delay_day"] == 1].iloc[0]

    with plt.rc_context(HOUSE_STYLE):
        figure = plt.figure(figsize=(15, 9.6))
        grid = figure.add_gridspec(2, 2, width_ratios=[1.15, 1.0], hspace=0.16, wspace=0.16, left=0.06, right=0.98, top=0.83, bottom=0.14)
        review_day_axes = figure.add_subplot(grid[0, 0])
        detractor_day_axes = figure.add_subplot(grid[1, 0], sharex=review_day_axes)
        review_bucket_axes = figure.add_subplot(grid[0, 1])
        detractor_bucket_axes = figure.add_subplot(grid[1, 1], sharex=review_bucket_axes)

        plot_day_series(review_day_axes, days, "mean_review", "review_ci_low", "review_ci_high")
        review_day_axes.set_ylim(1.0, 5.0)
        review_day_axes.set_ylabel("Mean review score (1–5)")
        review_day_axes.set_title("A. Daily SLA delay curve  ·  mean review score, 95% CI band")
        review_day_axes.tick_params(axis="x", labelbottom=False)
        review_day_axes.annotate(
            f"Review cliff: Day 0 → Day +1\n{day_zero['mean_review']:.2f} → {day_one['mean_review']:.2f} stars",
            xy=(1, day_one["mean_review"]), xytext=(3.2, 4.45),
            fontsize=8.5, color=INK_PRIMARY, ha="left", va="center",
            arrowprops={"arrowstyle": "-", "color": INK_SECONDARY, "linewidth": 0.8, "shrinkB": 4},
        )
        review_day_axes.text(
            -0.35, 1.25, "Promised delivery date (Day 0)", rotation=90, ha="right", va="bottom",
            fontsize=8, color=INK_SECONDARY,
        )

        plot_day_series(detractor_day_axes, days, "detractor_rate", "detractor_ci_low", "detractor_ci_high")
        detractor_day_axes.set_ylim(0, 100)
        detractor_day_axes.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        detractor_day_axes.set_ylabel("Severe detractor rate (1–2 stars)")
        detractor_day_axes.set_xlabel("SLA delay (days delivered after promised date; negative = early)")
        detractor_day_axes.set_xticks(range(-15, 16, 3))
        detractor_day_axes.set_xlim(-15.6, 15.6)
        detractor_day_axes.set_title("Severe detractor rate, Wilson 95% CI band", fontsize=9.5, fontweight="normal", color=INK_SECONDARY)
        threshold_jump = discontinuity["threshold_jump_day0_to_plus1"]
        placebo_jump = discontinuity["placebo_jump_minus1_to_day0"]
        detractor_day_axes.annotate(
            f"Day 0 → +1: {day_zero['detractor_rate']:.1f}% → {day_one['detractor_rate']:.1f}% "
            f"(+{threshold_jump['absolute_difference_pp']:.1f} pp, {threshold_jump['chi2_p_value_display'].replace('< ', 'p < ')})\n"
            f"Placebo Day −1 → 0: +{placebo_jump['absolute_difference_pp']:.1f} pp (p = {placebo_jump['chi2_p_value']:.2f})",
            xy=(1, day_one["detractor_rate"]), xytext=(-14.6, 62),
            fontsize=8.5, color=INK_PRIMARY, ha="left", va="center",
            arrowprops={"arrowstyle": "-", "color": INK_SECONDARY, "linewidth": 0.8, "shrinkB": 4},
        )

        review_bucket_axes.set_ylim(0, 5.0)
        plot_bucket_bars(review_bucket_axes, buckets, "mean_review", "review_ci_low", "review_ci_high", "{:.2f}")
        review_bucket_axes.set_ylabel("Mean review score (1–5)")
        review_bucket_axes.set_title("B. Grouped by SLA delay bucket  ·  mean review score, 95% CI")
        review_bucket_axes.tick_params(axis="x", labelbottom=False)

        detractor_bucket_axes.set_ylim(0, 100)
        plot_bucket_bars(detractor_bucket_axes, buckets, "detractor_rate", "detractor_ci_low", "detractor_ci_high", "{:.1f}%")
        detractor_bucket_axes.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        detractor_bucket_axes.set_ylabel("Severe detractor rate (1–2 stars)")
        detractor_bucket_axes.set_title("Severe detractor rate, Wilson 95% CI", fontsize=9.5, fontweight="normal", color=INK_SECONDARY)
        detractor_bucket_axes.set_xticks(
            np.arange(len(buckets)),
            labels=[f"{SLA_BUCKET_LABELS[bucket]}\nn = {orders:,}" for bucket, orders in zip(buckets["bucket"], buckets["orders"])],
        )
        detractor_bucket_axes.set_xlabel("SLA delay bucket (n = delivered orders)")

        legend_handles = [
            Patch(facecolor=ON_TIME_COLOR, label="On time or early (delay ≤ 0 days)"),
            Patch(facecolor=BREACH_COLOR, label="SLA breached (delay > 0 days)"),
            Line2D([0], [0], color=INK_SECONDARY, linewidth=0.9, linestyle=(0, (4, 3)), label="Promised delivery date"),
        ]
        figure.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(0.055, 0.885), ncol=3, handlelength=1.6, columnspacing=2.2)
        on_time_bucket_mean = float(buckets["mean_review"].iloc[2])
        early_reward = float(buckets["mean_review"].iloc[0]) - on_time_bucket_mean
        late_penalty = float(buckets["mean_review"].iloc[-1]) - on_time_bucket_mean
        add_figure_header(
            figure,
            "Missing the promised delivery date by even one day triggers a review-score cliff",
            f"Breached orders average {review_test['sla_breached']['mean']:.2f} stars vs {review_test['on_time']['mean']:.2f} on time "
            f"(Δ = {signed_number(review_test['mean_difference_breached_minus_on_time'], 2)}, "
            f"Welch {review_test['welch_p_value_display'].replace('< ', 'p < ')}). "
            f"The response is asymmetric: >7 days early earns {signed_number(early_reward, 2)} stars vs Day 0, "
            f">7 days late costs {signed_number(late_penalty, 2)}.",
            left=0.02,
            top=0.945,
        )
        add_provenance_note(
            figure,
            "sla_delay_days = order_delivered_customer_date − order_estimated_delivery_date (whole days). "
            "Severe detractor = order-level mean review ≤ 2. Panel A shows days −15…+15; Panel B covers all delivered orders.",
            left=0.02,
            bottom=0.055,
        )
        return save_figure(figure, output_path)


def load_seller_gmv() -> np.ndarray:
    with connect_read_only() as connection:
        return connection.execute("SELECT seller_gmv FROM mart_seller_pareto").df()["seller_gmv"].to_numpy(dtype=float)


def draw_pareto_crosshair(axes: Axes, top_seller_share_pct: float, gmv_share_pct: float, label_y_offset: float) -> None:
    point_x = 100.0 - top_seller_share_pct
    point_y = 100.0 - gmv_share_pct
    axes.plot([point_x, point_x], [0, point_y], color=INK_SECONDARY, linewidth=0.8, zorder=2)
    axes.plot([0, point_x], [point_y, point_y], color=INK_SECONDARY, linewidth=0.8, zorder=2)
    axes.plot(point_x, point_y, marker="o", markersize=6, color=INK_PRIMARY, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4)
    axes.text(
        point_x - 1.5, point_y + label_y_offset,
        f"Top {top_seller_share_pct:.1f}% of sellers = {gmv_share_pct:.0f}% of GMV",
        ha="right", va="bottom", fontsize=8.5, color=INK_PRIMARY,
        bbox={"boxstyle": "square,pad=0.15", "facecolor": SURFACE, "edgecolor": "none"},
    )


def plot_seller_pareto_lorenz(metrics: dict[str, Any], output_path: Path) -> Path:
    concentration = metrics["seller_concentration"]
    tiers = pd.DataFrame(concentration["pareto_tiers"])
    seller_share, gmv_share = lorenz_curve(load_seller_gmv())
    seller_share_pct = 100.0 * seller_share
    gmv_share_pct = 100.0 * gmv_share

    with plt.rc_context(HOUSE_STYLE):
        figure = plt.figure(figsize=(15, 6.6))
        grid = figure.add_gridspec(1, 3, width_ratios=[1.45, 1.0, 1.0], wspace=0.28, left=0.05, right=0.98, top=0.80, bottom=0.2)
        lorenz_axes = figure.add_subplot(grid[0, 0])
        breach_axes = figure.add_subplot(grid[0, 1])
        review_axes = figure.add_subplot(grid[0, 2])

        lorenz_axes.plot([0, 100], [0, 100], color=INK_MUTED, linewidth=1.0, label="Perfect equality (45° line)")
        lorenz_axes.fill_between(seller_share_pct, gmv_share_pct, seller_share_pct, color=ON_TIME_COLOR, alpha=0.12, linewidth=0, label="Gini area")
        lorenz_axes.plot(seller_share_pct, gmv_share_pct, color=ON_TIME_COLOR, linewidth=2.0, label="Seller GMV Lorenz curve")
        draw_pareto_crosshair(lorenz_axes, concentration["sellers_for_80pct_gmv"]["seller_share_pct"], 80.0, 2.0)
        draw_pareto_crosshair(lorenz_axes, concentration["sellers_for_50pct_gmv"]["seller_share_pct"], 50.0, 2.0)
        lorenz_axes.text(
            3, 94,
            f"Gini = {concentration['gini_coefficient']:.3f}\n"
            f"95% bootstrap CI [{concentration['gini_bootstrap_ci_low']:.3f}, {concentration['gini_bootstrap_ci_high']:.3f}]\n"
            f"{concentration['sellers_with_delivered_orders']:,} sellers with delivered orders",
            ha="left", va="top", fontsize=9, color=INK_PRIMARY, linespacing=1.5,
        )
        lorenz_axes.set_xlim(0, 100)
        lorenz_axes.set_ylim(0, 100)
        lorenz_axes.xaxis.set_major_formatter(PercentFormatter(decimals=0))
        lorenz_axes.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        lorenz_axes.set_xlabel("Cumulative share of sellers (ranked from smallest to largest GMV)")
        lorenz_axes.set_ylabel("Cumulative share of platform GMV")
        lorenz_axes.set_title("A. Seller GMV Lorenz curve")
        lorenz_axes.grid(True)
        lorenz_axes.legend(loc="center left", bbox_to_anchor=(0.0, 0.62))

        positions = np.arange(len(tiers))
        breach_rates = np.array([tier["sla_breach"]["rate_pct"] for tier in concentration["pareto_tiers"]])
        breach_errors = np.vstack([
            breach_rates - np.array([tier["sla_breach"]["ci_low_pct"] for tier in concentration["pareto_tiers"]]),
            np.array([tier["sla_breach"]["ci_high_pct"] for tier in concentration["pareto_tiers"]]) - breach_rates,
        ])
        tier_labels = [
            f"{TIER_LABELS[tier['pareto_tier']]}\n{tier['sellers']:,} sellers\n{tier['gmv_share_pct']:.1f}% of GMV"
            for tier in concentration["pareto_tiers"]
        ]
        breach_axes.bar(
            positions, breach_rates, width=0.5, color=list(TIER_COLORS), yerr=breach_errors,
            error_kw={"ecolor": INK_SECONDARY, "elinewidth": 0.9, "capsize": 3, "capthick": 0.9},
        )
        for position, rate, upper in zip(positions, breach_rates, breach_rates + breach_errors[1]):
            breach_axes.text(position, upper + 0.15, f"{rate:.1f}%", ha="center", va="bottom", fontsize=9, color=INK_PRIMARY)
        breach_axes.set_ylim(0, max(10.0, float((breach_rates + breach_errors[1]).max()) * 1.25))
        breach_axes.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        breach_axes.set_xticks(positions, labels=tier_labels)
        breach_axes.set_ylabel("SLA breach rate (share of seller-orders)")
        tier_test = concentration["tier_sla_breach_independence_test"]
        breach_axes.set_title(f"B1. SLA breach rate by Pareto tier\n(Wilson 95% CI; χ² p = {tier_test['p_value']:.4f})")
        breach_axes.grid(axis="y")

        review_scores = tiers["order_weighted_mean_review_score"].to_numpy(dtype=float)
        review_axes.scatter(positions, review_scores, s=70, color=list(TIER_COLORS), edgecolors=SURFACE, linewidths=1.5, zorder=3)
        for position, score in zip(positions, review_scores):
            review_axes.text(position, score + 0.02, f"{score:.2f}", ha="center", va="bottom", fontsize=9, color=INK_PRIMARY)
        review_axes.set_ylim(3.8, 4.4)
        review_axes.set_xlim(-0.6, len(tiers) - 0.4)
        review_axes.set_xticks(positions, labels=tier_labels)
        review_axes.set_ylabel("Mean review score (order-weighted)")
        review_axes.set_title("B2. Mean review score by Pareto tier\n(axis starts at 3.8 to show the spread)")
        review_axes.grid(axis="y")

        top_tier = concentration["pareto_tiers"][0]
        long_tail_tier = concentration["pareto_tiers"][-1]
        top_breach = top_tier["sla_breach"]["rate_pct"]
        long_tail_breach = long_tail_tier["sla_breach"]["rate_pct"]
        reliability_clause = (
            f"yet their SLA breach rate ({top_breach:.1f}%) is no lower than the long tail's ({long_tail_breach:.1f}%) — "
            "scale has not bought fulfilment reliability."
            if top_breach >= long_tail_breach
            else f"and breach less often than the long tail ({top_breach:.1f}% vs {long_tail_breach:.1f}%)."
        )
        add_figure_header(
            figure,
            f"GMV is highly concentrated: the top {concentration['sellers_for_80pct_gmv']['seller_share_pct']:.1f}% of sellers generate 80% of platform GMV",
            f"Top-10% sellers carry {top_tier['gmv_share_pct']:.1f}% of GMV at {top_tier['orders_per_seller']:.0f} orders/seller, "
            f"{reliability_clause}",
            left=0.02,
            top=0.93,
        )
        add_provenance_note(
            figure,
            "Seller GMV = Σ(price + freight) over delivered order items. Tiers by GMV rank: top 10%, next 40%, bottom 50%. "
            "Gini via trapezoidal Lorenz integration (sellers ascending, [0,0] prepended); CI from 2,000 seller bootstrap resamples (seed 42).",
            left=0.02,
            bottom=0.035,
        )
        return save_figure(figure, output_path)


def odds_ratio_tick_formatter(value: float, _position: int) -> str:
    return f"{value:g}"


def plot_model_forest(axes: Axes, model: dict[str, Any], title: str) -> None:
    terms = [term for term in model["terms"] if term["term"] != "const"]
    row_positions = np.arange(len(terms))[::-1]
    label_transform = blended_transform_factory(axes.transAxes, axes.transData)
    for row_position, term in zip(row_positions, terms):
        is_exposure = term["term"] == model["exposure"]
        color = BREACH_COLOR if is_exposure else INK_SECONDARY
        axes.hlines(row_position, term["or_ci_low"], term["or_ci_high"], color=color, linewidth=2.0)
        axes.plot(
            term["odds_ratio"], row_position, marker="s", markersize=7 if is_exposure else 6,
            color=color, markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=3,
        )
        axes.text(
            1.02, row_position,
            f"{term['odds_ratio']:.2f}  [{term['or_ci_low']:.2f}, {term['or_ci_high']:.2f}]",
            transform=label_transform, ha="left", va="center", fontsize=9,
            color=INK_PRIMARY, fontweight="semibold" if is_exposure else "normal",
        )
        axes.text(
            1.25, row_position, format_p_value(term["p_value"]),
            transform=label_transform, ha="left", va="center", fontsize=9, color=INK_SECONDARY,
        )
    axes.text(1.02, len(terms) - 0.35, "Adjusted OR  [95% CI]", transform=label_transform, ha="left", va="bottom", fontsize=8.5, color=INK_MUTED)
    axes.text(1.25, len(terms) - 0.35, "p-value", transform=label_transform, ha="left", va="bottom", fontsize=8.5, color=INK_MUTED)
    axes.axvline(1.0, color=INK_PRIMARY, linewidth=0.9, linestyle=(0, (4, 3)), zorder=1)
    lower_bound = min(term["or_ci_low"] for term in terms)
    upper_bound = max(term["or_ci_high"] for term in terms)
    axes.set_xscale("log")
    axes.set_xlim(min(0.8, lower_bound / 1.35), max(1.25, upper_bound * 1.35))
    candidate_ticks = [0.5, 0.6, 0.7, 0.8, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0, 30.0]
    axes.set_xticks([tick for tick in candidate_ticks if axes.get_xlim()[0] <= tick <= axes.get_xlim()[1]])
    axes.xaxis.set_major_formatter(FuncFormatter(odds_ratio_tick_formatter))
    axes.xaxis.set_minor_formatter(NullFormatter())
    axes.set_yticks(row_positions, labels=[FEATURE_LABELS[term["term"]] for term in terms])
    axes.set_ylim(-0.7, len(terms) - 0.3)
    axes.tick_params(axis="y", length=0)
    axes.spines["left"].set_visible(False)
    axes.grid(axis="x", which="major")
    axes.set_xlabel("Adjusted odds ratio (log scale; < 1 lowers the odds, > 1 raises them)")
    axes.set_title(title)
    axes.text(
        0.0, 1.0,
        f"n = {model['n_obs']:,} · events = {model['n_events']:,} ({model['event_rate_pct']:.1f}%) · "
        f"McFadden R² = {model['pseudo_r2_mcfadden']:.3f} · ROC AUC = {model['roc_auc']:.2f} · converged = {model['converged']}",
        transform=axes.transAxes, ha="left", va="bottom", fontsize=8.5, color=INK_SECONDARY,
    )


def plot_logit_odds_ratio_forest(metrics: dict[str, Any], output_path: Path) -> Path:
    models = metrics["logistic_models"]
    model_one = models["model_1_severe_detractor"]
    model_two = models["model_2_repeat_buyer"]
    model_one_exposure = model_one["exposure_effect"]
    model_two_exposure = model_two["exposure_effect"]
    with plt.rc_context(HOUSE_STYLE):
        figure = plt.figure(figsize=(12, 9.4))
        grid = figure.add_gridspec(2, 1, hspace=0.62, left=0.22, right=0.72, top=0.83, bottom=0.15)
        plot_model_forest(
            figure.add_subplot(grid[0, 0]), model_one,
            "A. Model 1 — Customer experience: P(severe detractor review, 1–2 stars), all reviewed delivered orders\n",
        )
        plot_model_forest(
            figure.add_subplot(grid[1, 0]), model_two,
            "B. Model 2 — Retention: P(customer becomes a repeat buyer), first delivered order per customer\n",
        )
        add_figure_header(
            figure,
            "An SLA breach is the dominant driver of 1–2 star reviews; its retention effect is small",
            f"Model 1: breach raises P(severe detractor) by {model_one_exposure['average_marginal_effect_pp']:.1f} pp on average "
            f"(AME, 95% CI [{model_one_exposure['average_marginal_effect_ci_low_pp']:.1f}, {model_one_exposure['average_marginal_effect_ci_high_pp']:.1f}]). "
            f"Model 2: breach shifts P(repeat) by {signed_number(model_two_exposure['average_marginal_effect_pp'], 2)} pp on a "
            f"{model_two['event_rate_pct']:.1f}% base.",
            left=0.02,
            top=0.93,
        )
        add_provenance_note(
            figure,
            "Logistic regression (statsmodels Logit, MLE) with HC0 heteroskedasticity-robust standard errors. "
            "Complete cases on review_score, order_gmv, freight_ratio, delivery_distance_km. Orange = exposure of interest; grey = controls.",
            left=0.02,
            bottom=0.055,
        )
        return save_figure(figure, output_path)


def render_all_figures(metrics: dict[str, Any] | None = None, output_dir: Path = OUTPUT_DIR) -> list[Path]:
    resolved_metrics = metrics if metrics is not None else load_metrics(METRICS_PATH)
    output_paths = [output_dir / file_name for file_name in FIGURE_FILENAMES]
    return [
        plot_cohort_retention_heatmap(output_paths[0]),
        plot_sla_breach_penalty_curve(resolved_metrics, output_paths[1]),
        plot_seller_pareto_lorenz(resolved_metrics, output_paths[2]),
        plot_logit_odds_ratio_forest(resolved_metrics, output_paths[3]),
    ]
