#!/usr/bin/env python3
"""
E-commerce Growth Marketing Dashboard (Streamlit)
===================================================
pipeline.py가 적재한 SQLite 마트 테이블을 실시간 조회·시각화합니다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DB_CANDIDATES = (PROJECT_ROOT / "ecommerce.db", PROJECT_ROOT / "portfolio.db")

FUNNEL_STAGES = [
    ("total_visitors", "방문"),
    ("product_views", "상품 조회"),
    ("add_to_cart_count", "장바구니"),
    ("checkout_started_count", "결제 시작"),
    ("purchase_completed_count", "구매 완료"),
]

SEGMENT_ACTION_LABELS = {
    "VIP": "얼리 액세스 · 리퍼럴 프로그램",
    "이탈위기": "Win-back 쿠폰 발송",
    "신규": "온보딩 시리즈 (D+1~D+7)",
    "겨울잠": "시즌 큐레이션 DM",
}

SEGMENT_BADGE_CLASS = {
    "VIP": "pos",
    "이탈위기": "neg",
    "신규": "accent",
    "겨울잠": "muted",
}

CASE_STUDY_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');
  :root{
    --cs-bg-panel:#f8fafc; --cs-line:#e2e8f0; --cs-accent-blue:#1d4ed8; --cs-accent-cyan:#0369a1;
    --cs-accent-green:#15803d; --cs-accent-red:#dc2626; --cs-text-main:#0f172a; --cs-text-sub:#64748b;
    --cs-text-faint:#94a3b8; --cs-shadow:0 1px 2px rgba(15,23,42,0.04), 0 4px 14px rgba(15,23,42,0.04);
    --cs-font-display:'Sora',sans-serif; --cs-font-mono:'JetBrains Mono',monospace;
  }
  .cs-panel{
    background:var(--cs-bg-panel); border:1px solid var(--cs-line); border-radius:14px;
    padding:20px 22px; box-shadow:var(--cs-shadow); margin-bottom:18px;
  }
  .cs-panel-title{
    font-size:12px; color:var(--cs-accent-cyan); text-transform:uppercase; letter-spacing:0.12em;
    font-weight:700; margin-bottom:14px; font-family:var(--cs-font-mono);
    display:flex; align-items:center; gap:8px;
  }
  .cs-panel-title .cs-pt-line{ flex:1; height:1px; background:var(--cs-line); }
  .cs-table-scroll{ overflow-x:auto; }
  .cs-table{ width:100%; border-collapse:collapse; font-family:var(--cs-font-mono); font-size:12.5px; font-variant-numeric:tabular-nums; }
  .cs-table th{
    background:rgba(29,78,216,0.06); color:var(--cs-accent-cyan); text-align:left; padding:9px 12px;
    font-weight:700; border-bottom:1px solid var(--cs-line); font-size:10.5px; letter-spacing:0.06em;
    text-transform:uppercase; white-space:nowrap;
  }
  .cs-table td{ padding:9px 12px; border-bottom:1px solid var(--cs-line); color:var(--cs-text-main); white-space:nowrap; }
  .cs-table tr:last-child td{ border-bottom:none; }
  .cs-table .muted{ color:var(--cs-text-sub); }
  .cs-table .accent{ color:var(--cs-accent-cyan); font-weight:700; }
  .cs-table .neg{ color:var(--cs-accent-red); font-weight:700; }
  .cs-table .pos{ color:var(--cs-accent-green); font-weight:700; }
  .cs-insight{
    border:1px solid var(--cs-accent-blue); border-radius:12px; padding:16px 20px;
    background:rgba(29,78,216,0.04); font-size:13.5px; color:var(--cs-text-sub); line-height:1.75;
    display:flex; gap:12px; align-items:flex-start; margin-bottom:8px;
  }
  .cs-insight .cs-ib-icon{ font-size:18px; flex-shrink:0; }
  .cs-insight b{ color:var(--cs-text-main); }
  .cs-tag{
    display:inline-flex; align-items:center; gap:8px; font-size:12px; letter-spacing:0.18em;
    text-transform:uppercase; color:var(--cs-accent-cyan); font-weight:700; margin-bottom:10px;
    font-family:var(--cs-font-mono);
  }
  .cs-tag::before{ content:""; width:24px; height:1px; background:var(--cs-accent-cyan); display:inline-block; }
  .cs-case-title{ font-family:var(--cs-font-display); font-size:26px; font-weight:800; color:var(--cs-text-main); margin-bottom:10px; }
  .cs-case-sub{ font-size:14px; color:var(--cs-text-sub); line-height:1.75; max-width:820px; margin-bottom:22px; }
  .cs-case-sub b{ color:var(--cs-text-main); }
  .cs-case-sub .cs-arrow{ color:var(--cs-accent-cyan); font-weight:700; }
</style>
"""

CRM_SCENARIOS = {
    "이탈위기": (
        "**이탈 위기 고객 CRM 시나리오**\n\n"
        "1. **Win-back 쿠폰**: 최근 30일 미구매 + 과거 3회 이상 구매 고객에게 "
        "15% 할인 쿠폰 (유효기간 7일) — 푸시 + 카카오 알림톡\n"
        "2. **장바구니 리마인드**: 결제 시작 후 이탈 이력이 있는 고객 대상 "
        "'담아두신 상품, 오늘까지 무료배송' 메시지\n"
        "3. **VIP 승급 유도**: Monetary 상위 30% 중 Recency 저하 그룹에 "
        "멤버십 등급 유지 조건 안내\n"
        "4. **A/B 테스트**: UTM별 이탈 구간(장바구니→결제) CTA 문구 2종 비교"
    ),
    "겨울잠": (
        "**겨울잠 고객 재활성화 시나리오**\n\n"
        "1. **시즌 큐레이션 DM**: 90일+ 미구매 고객에게 베스트셀러 TOP5 이메일\n"
        "2. **저마진 재유입**: 5,000원 즉시할인 + 무료반품 프로모션 (1회 한정)\n"
        "3. **크로스셀**: 과거 구매 카테고리 연관 상품 추천 (협업필터링)"
    ),
    "신규": (
        "**신규 고객 육성 시나리오**\n\n"
        "1. **온보딩 시리즈**: 가입 D+1 환영, D+3 리뷰 유도, D+7 2차 구매 쿠폰\n"
        "2. **첫 재구매 촉진**: 14일 내 재구매 시 적립금 2배 이벤트"
    ),
    "VIP": (
        "**VIP 유지·확장 시나리오**\n\n"
        "1. **얼리 액세스**: 신상품 선공개 + 전용 CS 라인\n"
        "2. **리퍼럴 프로그램**: VIP 추천 코드 발급 — 추천인·피추천인 모두 적립"
    ),
}


def resolve_db_path() -> Path:
    for path in DB_CANDIDATES:
        if path.exists():
            return path

    # 클라우드 배포 시 앱 소스 체크아웃 디렉터리가 읽기 전용일 수 있음(예:
    # Streamlit Community Cloud의 /mount/src/...) — 새 DB를 만들기 전에 쓰기
    # 가능 여부를 확인하고, 안 되면 임시 디렉터리로 폴백한다.
    candidate = DB_CANDIDATES[0]
    try:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        probe = candidate.parent / ".write_test"
        probe.touch()
        probe.unlink()
        return candidate
    except OSError:
        import tempfile

        return Path(tempfile.gettempdir()) / "ecommerce.db"


@st.cache_resource
def get_connection(db_path: str) -> sqlite3.Connection:
    # sqlite3.connect('ecommerce.db') — pipeline 적재 DB 실시간 조회
    return sqlite3.connect(db_path, check_same_thread=False)


@st.cache_data(ttl=60)
def load_table(db_path: str, table_name: str) -> pd.DataFrame:
    conn = get_connection(db_path)
    return pd.read_sql(f"SELECT * FROM {table_name}", conn)


@st.cache_data(ttl=60)
def load_pipeline_stats(db_path: str) -> dict:
    conn = get_connection(db_path)
    stats: dict = {}

    tables = [
        "raw_ecommerce_orders",
        "raw_user_behavior_logs",
        "stg_ecommerce_orders",
        "stg_user_behavior_logs",
        "mart_user_funnel_daily",
        "mart_user_rfm_scores",
    ]
    for table in tables:
        try:
            row = pd.read_sql(f"SELECT COUNT(*) AS cnt FROM {table}", conn)
            stats[table] = int(row["cnt"].iloc[0])
        except Exception:
            stats[table] = None

    last_updated = pd.read_sql(
        """
        SELECT MAX(latest_ts) AS last_updated FROM (
            SELECT MAX(event_at) AS latest_ts FROM stg_user_behavior_logs
            UNION ALL
            SELECT MAX(paid_at)   AS latest_ts FROM stg_ecommerce_orders
        )
        """,
        conn,
    )
    stats["last_updated"] = last_updated["last_updated"].iloc[0]
    stats["db_file_mtime"] = datetime.fromtimestamp(
        Path(db_path).stat().st_mtime
    ).strftime("%Y-%m-%d %H:%M:%S")
    return stats


def compute_funnel_metrics(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {col: 0 for col, _ in FUNNEL_STAGES}

    return {
        col: float(df[col].sum()) if col in df.columns else 0
        for col, _ in FUNNEL_STAGES
    }


def build_stage_detail_table(metrics: dict[str, float]) -> pd.DataFrame:
    """GA4 퍼널 탐색 형식의 단계별 상세 테이블(인원수 · 전체대비 · 이전단계대비 · 이탈률)."""
    stages = [(label, metrics[key]) for key, label in FUNNEL_STAGES]
    total = stages[0][1] if stages else 0

    rows = []
    prev_val = None
    for label, val in stages:
        pct_of_total = (val / total * 100) if total > 0 else 0.0
        if prev_val is None:
            pct_of_prev = 100.0
            drop_rate = 0.0
        else:
            pct_of_prev = (val / prev_val * 100) if prev_val > 0 else 0.0
            drop_rate = 100.0 - pct_of_prev
        rows.append(
            {
                "단계": label,
                "인원수": int(val),
                "전체 대비 비율": pct_of_total,
                "이전 단계 대비 유지율": pct_of_prev,
                "이탈률": drop_rate,
            }
        )
        prev_val = val

    return pd.DataFrame(rows)


def build_funnel_trend(filtered: pd.DataFrame) -> pd.DataFrame:
    """일자별 단계 합계 + 종합 CVR 추이."""
    stage_cols = [col for col, _ in FUNNEL_STAGES]
    daily = filtered.groupby("base_date")[stage_cols].sum().reset_index()
    daily = daily.sort_values("base_date")
    daily["cvr"] = daily.apply(
        lambda r: (r["purchase_completed_count"] / r["total_visitors"] * 100)
        if r["total_visitors"] > 0
        else 0.0,
        axis=1,
    )
    return daily


def build_segment_breakdown(filtered: pd.DataFrame, dimension: str) -> pd.DataFrame:
    """선택한 측정기준(플랫폼/UTM Source)별 최종 CVR 비교."""
    stage_cols = [col for col, _ in FUNNEL_STAGES]
    grouped = filtered.groupby(dimension)[stage_cols].sum().reset_index()
    grouped["cvr"] = grouped.apply(
        lambda r: (r["purchase_completed_count"] / r["total_visitors"] * 100)
        if r["total_visitors"] > 0
        else 0.0,
        axis=1,
    )
    return grouped.sort_values("cvr", ascending=False)


def render_pipeline_tab(db_path: str) -> None:
    st.subheader("⚙️ 파이프라인 모니터링")

    st.markdown(
        """
        **자동 적재 파이프라인** — `API 호출` → `RAW JSON` → `컬럼 표준화` → `Data Mart`
        """
    )

    stages = [
        ("1 · AI GENERATED", "API 호출 스크립트", "stages/api_client.py"),
        ("2 · RAW", "원본 JSON 수집", "raw_* + data/raw/"),
        ("3 · HUMAN DEFINED", "컬럼 표준화 · Staging", "stages/transform.py"),
        ("4 · DB", "mart_user_funnel_daily · mart_user_rfm_scores", "sql/03_etl_staging_to_mart.sql"),
    ]
    cols = st.columns(4)
    for col, (badge, title, detail) in zip(cols, stages):
        with col:
            st.markdown(f"**{badge}**")
            st.caption(title)
            st.code(detail, language=None)

    with st.expander("📖 데이터 출처 & 집계 기준 열람", expanded=False):
        src_tab, criteria_tab, rfm_tab = st.tabs(
            ["데이터 출처 · 수집 방식", "퍼널 지표 정의", "RFM 세그먼트 기준"]
        )

        with src_tab:
            st.markdown(
                """
                | 구분 | 내용 |
                |---|---|
                | **소스 시스템** | NAVER Commerce API · Amazon SP-API (현재는 Mock 응답 — 실 운영 시 API Key 기반 실호출로 교체) |
                | **수집 단위** | 주문(Order) JSON + 사용자 행동 로그(behavior log) JSON, 일자별 배치 |
                | **원본 보존** | RAW Zone에 표준화 이전 원본 JSON 그대로 적재 (재처리·검증용) |
                | **환율 처리** | Amazon(USD) 주문은 수집 시점 환율로 KRW 환산 후 표준화 |
                | **시간대 처리** | Amazon 응답은 UTC(Z suffix) → KST(+9h)로 변환 후 저장 |
                """
            )

        with criteria_tab:
            st.markdown(
                """
                | 구분 | 내용 |
                |---|---|
                | **주문 Lookback** | 14일 — 최근 14일 주문을 매일 재수집해 취소·환불 상태 변경을 반영 |
                | **행동 로그 Lookback** | 없음(0일) — 로그는 발생 후 불변이라 당일 수집분만 적재 |
                | **Mart 재계산 범위** | `mart_user_funnel_daily`는 [run_date − 14일, run_date] 구간만 삭제 후 재계산(증분), 구간 밖 과거 데이터는 보존 |
                | **RFM 재계산 범위** | 매번 전체 재적재 — Recency가 신규 주문 여부와 무관하게 매일 전체 유저 기준으로 변하기 때문 |
                | **방문(total_visitors)** | 세션 단위 고유 방문자 수 |
                | **상품 조회** | `view_item` 이벤트 발생 건 |
                | **장바구니** | `add_to_cart` 이벤트 발생 건 |
                | **결제 시작** | `begin_checkout` 이벤트 발생 건 |
                | **구매 완료** | `purchase` 이벤트 발생 건 (결제 완료 주문과 매칭) |
                """
            )

        with rfm_tab:
            st.markdown(
                """
                RFM 3요소를 각각 5분위(NTILE 5)로 점수화한 뒤 아래 규칙으로 세그먼트를 분류합니다.

                | 세그먼트 | 조건 |
                |---|---|
                | **VIP** | R≥4 AND F≥4 AND M≥4 |
                | **이탈위기** | R≤2 AND (F≥3 OR M≥3) — 과거 우수 고객의 최근 이탈 징후 |
                | **신규** | F=1 AND R≥4 — 최근 첫 구매 고객 |
                | **겨울잠** | R≤2 AND F≤2 AND M≤2 — 장기 비활성 저가치 |
                | 그 외 | F·M 가중치로 VIP/이탈위기/겨울잠 중 가장 가까운 세그먼트에 매핑 |

                - **R (Recency)**: 마지막 구매일로부터 경과일 — 최근일수록 높은 점수
                - **F (Frequency)**: 누적 구매 건수(고유 주문 수)
                - **M (Monetary)**: 누적 결제 금액 합계
                """
            )

        st.caption("기준 원본: `sql/03_etl_staging_to_mart.sql`, `stages/clean_transform.py`, `stages/api_client.py`")

    try:
        stats = load_pipeline_stats(db_path)
    except Exception as exc:
        st.error(f"DB 연결 실패: {exc}")
        st.info("`python pipeline.py` 실행 후 새로고침해 주세요.")
        return

    all_ok = all(
        stats.get(t) is not None and stats[t] > 0
        for t in ("raw_user_behavior_logs", "stg_user_behavior_logs", "mart_user_funnel_daily")
    )

    if all_ok:
        st.success("✅ 파이프라인 정상 가동 중 — RAW → Staging → Mart 4단계 적재 확인")
    else:
        st.warning("⚠️ 일부 Zone에 데이터가 없습니다. `python pipeline.py`를 실행해 주세요.")

    st.markdown("##### Zone별 Row Count")
    st.caption("RAW→Staging→Mart 각 단계가 정상 통과됐는지 확인하는 파이프라인 헬스체크입니다. (분석 지표 아님 — 0이면 해당 단계 실패를 의심)")
    z1, z2, z3 = st.columns(3)
    with z1:
        st.metric("RAW — 주문 JSON", f"{stats.get('raw_ecommerce_orders', 0):,}")
        st.metric("RAW — 행동 JSON", f"{stats.get('raw_user_behavior_logs', 0):,}")
    with z2:
        st.metric("Staging — 주문", f"{stats.get('stg_ecommerce_orders', 0):,}")
        st.metric("Staging — 행동 로그", f"{stats.get('stg_user_behavior_logs', 0):,}")
    with z3:
        st.metric("Mart — 퍼널", f"{stats.get('mart_user_funnel_daily', 0):,}")
        st.metric("Mart — RFM", f"{stats.get('mart_user_rfm_scores', 0):,}")

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**최근 Staging 데이터 시각**")
        st.write(stats.get("last_updated") or "—")
    with c2:
        st.markdown("**DB 파일 갱신 시각**")
        st.write(stats.get("db_file_mtime", "—"))

    st.caption(f"연결 DB: `{db_path}`")


def render_funnel_tab(db_path: str) -> None:
    st.subheader("🎯 퍼널 분석")

    try:
        funnel_df = load_table(db_path, "mart_user_funnel_daily")
    except Exception as exc:
        st.error(f"마트 테이블 조회 실패: {exc}")
        return

    if funnel_df.empty:
        st.warning("mart_user_funnel_daily에 데이터가 없습니다.")
        return

    funnel_df["base_date"] = pd.to_datetime(funnel_df["base_date"])

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    platforms = sorted(funnel_df["platform"].unique())
    utm_options = sorted(funnel_df["utm_source"].unique())
    min_date = funnel_df["base_date"].min().date()
    max_date = funnel_df["base_date"].max().date()

    with filter_col1:
        selected_platforms = st.multiselect(
            "플랫폼",
            options=platforms,
            default=platforms,
        )
    with filter_col2:
        selected_utms = st.multiselect(
            "UTM Source",
            options=utm_options,
            default=utm_options,
        )
    with filter_col3:
        date_range = st.date_input(
            "기간",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

    filtered = funnel_df.copy()
    if selected_platforms:
        filtered = filtered[filtered["platform"].isin(selected_platforms)]
    if selected_utms:
        filtered = filtered[filtered["utm_source"].isin(selected_utms)]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        filtered = filtered[
            (filtered["base_date"].dt.date >= start)
            & (filtered["base_date"].dt.date <= end)
        ]

    if filtered.empty:
        st.info("선택한 필터 조건에 해당하는 데이터가 없습니다.")
        return

    metrics = compute_funnel_metrics(filtered)
    stage_labels = [label for _, label in FUNNEL_STAGES]
    stage_values = [metrics[key] for key, _ in FUNNEL_STAGES]

    # --- A. 상단 요약 지표 -------------------------------------------------
    total_visitors = filtered["total_visitors"].sum()
    total_purchases = filtered["purchase_completed_count"].sum()
    overall_cvr = (total_purchases / total_visitors * 100) if total_visitors > 0 else 0.0

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("총 진입수", f"{int(total_visitors):,}")
    kpi2.metric("최종 전환수", f"{int(total_purchases):,}")
    kpi3.metric("종합 CVR", f"{overall_cvr:.2f}%")
    kpi4.metric("집계 일수 · 행수", f"{filtered['base_date'].nunique()}일 · {len(filtered):,}건")

    st.divider()

    # --- B. 퍼널 시각화 -----------------------------------------------------
    chart_type = st.radio(
        "차트 유형",
        ["Funnel", "Bar"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if chart_type == "Funnel":
        fig = go.Figure(
            go.Funnel(
                y=stage_labels,
                x=stage_values,
                textinfo="value+percent initial+percent previous",
                marker={"color": px.colors.sequential.Blues_r},
            )
        )
        fig.update_layout(
            title="전환 퍼널 (전체 대비 % · 이전 단계 대비 %)",
            height=460,
            margin=dict(l=20, r=20, t=50, b=20),
        )
    else:
        fig = px.bar(
            x=stage_labels,
            y=stage_values,
            labels={"x": "단계", "y": "건수"},
            title="퍼널 단계별 건수 (Bar)",
            color=stage_values,
            color_continuous_scale="Blues",
        )
        fig.update_layout(height=460, showlegend=False)

    st.plotly_chart(fig)

    # --- C. 단계별 전환율 상세 테이블 --------------------------------------
    st.markdown("#### 📊 단계별 전환율 상세")
    detail_df = build_stage_detail_table(metrics)
    max_drop_idx = detail_df["이탈률"].idxmax() if len(detail_df) > 1 else None

    display_df = detail_df.copy()
    display_df["전체 대비 비율"] = display_df["전체 대비 비율"].map("{:.1f}%".format)
    display_df["이전 단계 대비 유지율"] = display_df["이전 단계 대비 유지율"].map("{:.1f}%".format)
    display_df["이탈률"] = display_df["이탈률"].map("{:.1f}%".format)
    display_df["인원수"] = display_df["인원수"].map("{:,}".format)

    def _highlight_max_drop(row):
        if max_drop_idx is not None and row.name == max_drop_idx and row.name != 0:
            return ["background-color: rgba(220,38,38,0.08)"] * len(row)
        return [""] * len(row)

    st.dataframe(
        display_df.style.apply(_highlight_max_drop, axis=1),
        width="stretch",
        hide_index=True,
    )

    st.divider()

    # --- D. 퍼널 추이 (트렌드) ------------------------------------------
    st.markdown("#### 📈 퍼널 추이")
    trend_metric = st.selectbox(
        "지표 선택",
        ["종합 CVR"] + stage_labels,
    )
    trend_df = build_funnel_trend(filtered)

    if trend_metric == "종합 CVR":
        trend_fig = px.line(
            trend_df, x="base_date", y="cvr",
            labels={"base_date": "일자", "cvr": "CVR (%)"},
            title="일자별 종합 CVR 추이",
            markers=True,
        )
    else:
        key_by_label = {label: key for key, label in FUNNEL_STAGES}
        col = key_by_label[trend_metric]
        trend_fig = px.line(
            trend_df, x="base_date", y=col,
            labels={"base_date": "일자", col: "인원수"},
            title=f"일자별 '{trend_metric}' 인원수 추이",
            markers=True,
        )
    trend_fig.update_layout(height=360)
    st.plotly_chart(trend_fig)

    st.divider()

    # --- E. 세그먼트 비교 (Breakdown) --------------------------------------
    st.markdown("#### 🔍 세그먼트 비교")
    breakdown_dim = st.radio(
        "비교 기준",
        ["platform", "utm_source"],
        format_func=lambda x: "플랫폼" if x == "platform" else "UTM Source",
        horizontal=True,
    )
    breakdown_df = build_segment_breakdown(filtered, breakdown_dim)
    breakdown_fig = px.bar(
        breakdown_df,
        x=breakdown_dim,
        y="cvr",
        labels={breakdown_dim: "플랫폼" if breakdown_dim == "platform" else "UTM Source", "cvr": "최종 CVR (%)"},
        title="세그먼트별 최종 CVR 비교",
        color="cvr",
        color_continuous_scale="Blues",
    )
    breakdown_fig.update_layout(height=360, showlegend=False)
    st.plotly_chart(breakdown_fig)

    with st.expander("원본 데이터 보기"):
        st.dataframe(
            filtered.sort_values("base_date", ascending=False),
            width="stretch",
            hide_index=True,
        )


def render_rfm_sample_panel(rfm_df: pd.DataFrame) -> None:
    """CASE 03(LLM 요약 테이블) 스타일 — 세그먼트별 대표 고객 샘플 + 추천 액션."""
    segment_order = ["VIP", "이탈위기", "신규", "겨울잠"]
    sample_rows = []
    for segment in segment_order:
        seg_df = rfm_df[rfm_df["segment_name"] == segment].sort_values(
            "monetary_amount", ascending=False
        )
        sample_rows.append(seg_df.head(2))
    sample_df = pd.concat(sample_rows) if sample_rows else rfm_df.head(0)

    rows_html = []
    for _, row in sample_df.iterrows():
        badge_cls = SEGMENT_BADGE_CLASS.get(row["segment_name"], "muted")
        action = SEGMENT_ACTION_LABELS.get(row["segment_name"], "-")
        rfm_summary = f"R{int(row['r_score'])} · F{int(row['f_score'])} · M{int(row['m_score'])}"
        rows_html.append(
            "<tr>"
            f"<td class='accent'>{row['user_id']}</td>"
            f"<td class='muted'>{row['last_purchase_date'] or '-'}</td>"
            f"<td class='muted'>{rfm_summary}</td>"
            f"<td>{row['monetary_amount']:,.0f}원</td>"
            f"<td class='{badge_cls}'>{row['segment_name']}</td>"
            f"<td class='muted'>{action}</td>"
            "</tr>"
        )

    table_html = f"""
    <div class="cs-panel">
      <div class="cs-panel-title">MART_USER_RFM_SCORES (SAMPLE ROWS)<span class="cs-pt-line"></span></div>
      <div class="cs-table-scroll">
        <table class="cs-table">
          <thead>
            <tr><th>user_id</th><th>last_purchase</th><th>R·F·M</th><th>monetary</th><th>segment</th><th>추천 액션</th></tr>
          </thead>
          <tbody>{''.join(rows_html)}</tbody>
        </table>
      </div>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)

    st.markdown(
        """
        <div class="cs-insight">
          <span class="cs-ib-icon">💡</span>
          <div>AI는 NTILE(5)로 R·F·M 분위를 나누고 세그먼트를 분류하는 건 순식간에 해낸다.
          하지만 <b>'이탈위기와 겨울잠을 가르는 임계값'</b>, <b>'어떤 세그먼트에 어떤 CRM 액션을 붙일지'</b>는
          도메인을 아는 사람만이 설계할 수 있는 영역 — 이 기준이 명확할 때 세그먼트가 실제 액션으로 이어졌음.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_rfm_tab(db_path: str) -> None:
    st.markdown(CASE_STUDY_CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="cs-tag">CASE 04 — 고객 세분화</div>
        <div class="cs-case-title">RFM 기반 고객 세분화 및 CRM 시나리오</div>
        <p class="cs-case-sub">
          <b>문제정의 :</b> 세그먼트 없이는 모든 고객에게 동일한 메시지를 보내 이탈 위기 고객도,
          VIP 고객도 같은 프로모션을 받았음.
          <span class="cs-arrow"> → </span>
          R·F·M 점수 기반으로 4개 세그먼트를 자동 분류하고, 세그먼트별 <b>CRM 액션을 매칭</b>한 테이블 생성.
        </p>
        """,
        unsafe_allow_html=True,
    )

    try:
        rfm_df = load_table(db_path, "mart_user_rfm_scores")
    except Exception as exc:
        st.error(f"RFM 마트 조회 실패: {exc}")
        return

    if rfm_df.empty:
        st.warning("mart_user_rfm_scores에 데이터가 없습니다.")
        return

    render_rfm_sample_panel(rfm_df)
    st.divider()

    segment_counts = (
        rfm_df.groupby("segment_name")
        .size()
        .reset_index(name="customer_count")
        .sort_values("customer_count", ascending=False)
    )
    segment_counts["pct"] = (
        segment_counts["customer_count"] / segment_counts["customer_count"].sum() * 100
    ).round(1)

    color_map = {
        "VIP": "#2ecc71",
        "이탈위기": "#e74c3c",
        "신규": "#3498db",
        "겨울잠": "#95a5a6",
    }

    fig = px.pie(
        segment_counts,
        names="segment_name",
        values="customer_count",
        title="RFM 세그먼트별 고객 수 비중",
        color="segment_name",
        color_discrete_map=color_map,
        hole=0.35,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(height=460, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig)

    m1, m2, m3, m4 = st.columns(4)
    for col, segment in zip([m1, m2, m3, m4], ["VIP", "이탈위기", "신규", "겨울잠"]):
        cnt = segment_counts.loc[
            segment_counts["segment_name"] == segment, "customer_count"
        ]
        col.metric(segment, f"{int(cnt.iloc[0]) if len(cnt) else 0:,}명")

    st.divider()

    churn_count = int(
        segment_counts.loc[
            segment_counts["segment_name"] == "이탈위기", "customer_count"
        ].sum()
    )
    churn_pct = float(
        segment_counts.loc[
            segment_counts["segment_name"] == "이탈위기", "pct"
        ].sum()
    )

    st.success(CRM_SCENARIOS["이탈위기"])

    with st.expander("세그먼트별 추가 CRM 시나리오"):
        for segment, text in CRM_SCENARIOS.items():
            if segment == "이탈위기":
                continue
            st.markdown(text)

    st.caption(
        f"이탈위기 고객 {churn_count:,}명 (전체의 {churn_pct:.1f}%) — "
        "위 시나리오 우선 실행 권장"
    )


def ensure_seeded(db_path: str) -> None:
    """DB가 비어있으면(예: 클라우드 배포 후 첫 기동) 파이프라인을 1회 자동 실행해 시드 데이터를 생성."""
    path = Path(db_path)
    needs_seed = True
    if path.exists():
        try:
            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM mart_user_funnel_daily").fetchone()[0]
            conn.close()
            needs_seed = count == 0
        except sqlite3.Error:
            needs_seed = True

    if not needs_seed:
        return

    with st.spinner("초기 데이터가 없어 파이프라인을 실행합니다 (14일치 mock 데이터 생성 중)..."):
        from datetime import date, timedelta

        import pipeline as pipeline_module

        pipeline_module.configure_logging()
        today = date.today()
        target_dates = [today - timedelta(days=i) for i in range(14)]
        pipeline_module.run_pipeline(
            db_path=path,
            target_dates=target_dates,
            sessions_per_day=80,
        )

    get_connection.clear()
    load_table.clear()
    load_pipeline_stats.clear()


def main() -> None:
    st.set_page_config(
        page_title="E-commerce Growth Dashboard",
        page_icon="📈",
        layout="wide",
    )

    db_path = str(resolve_db_path())
    ensure_seeded(db_path)

    st.title("📈 E-commerce Growth Marketing Dashboard")
    st.markdown(
        "네이버 · 아마존 멀티 플랫폼 **퍼널 전환** 및 **RFM 세그먼트** 분석 대시보드"
    )

    tab_pipeline, tab_funnel, tab_rfm = st.tabs(
        ["⚙️ 파이프라인", "🎯 퍼널 분석", "👥 고객 세분화(RFM)"]
    )

    with tab_pipeline:
        render_pipeline_tab(db_path)

    with tab_funnel:
        render_funnel_tab(db_path)

    with tab_rfm:
        render_rfm_tab(db_path)


if __name__ == "__main__":
    main()
