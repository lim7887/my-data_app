import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st


# -----------------------------
# 기본 설정
# -----------------------------

st.set_page_config(
    page_title="어제의 박스오피스",
    page_icon="🎬",
    layout="wide",
)

API_URL = (
    "https://www.kobis.or.kr/kobisopenapi/webservice/rest/"
    "boxoffice/searchDailyBoxOfficeList.json"
)

# KOBIS API는 호출 결과가 동일한 날짜라면 1시간 동안 캐시합니다.
CACHE_TTL = 60 * 60


# -----------------------------
# 어제 날짜 계산
# -----------------------------

def get_yesterday_kst():
    """서버의 시간대와 관계없이 한국 시간으로 어제 날짜를 구합니다."""
    kst = ZoneInfo("Asia/Seoul")
    now_kst = datetime.now(kst)
    yesterday = now_kst.date() - timedelta(days=1)

    # KOBIS가 요구하는 YYYYMMDD 형식으로 변환합니다.
    return yesterday.strftime("%Y%m%d")


# -----------------------------
# KOBIS API 호출
# -----------------------------

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_boxoffice(target_dt):
    """
    특정 날짜의 일일 박스오피스를 가져옵니다.

    같은 날짜를 다시 요청하면 캐시된 결과를 사용하여
    약 1시간 동안 KOBIS API를 다시 호출하지 않습니다.
    """
    # 인증키는 코드에 직접 적지 않고 Streamlit Secrets에서 읽습니다.
    try:
        api_key = st.secrets["KOBIS_KEY"]
    except KeyError:
        raise RuntimeError(
            "KOBIS_KEY를 찾을 수 없습니다. "
            "Streamlit Cloud의 Settings → Secrets에 "
            "KOBIS_KEY를 등록했는지 확인하세요."
        )

    params = {
        "key": api_key,
        "targetDt": target_dt,
    }

    try:
        response = requests.get(
            API_URL,
            params=params,
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"KOBIS API 요청에 실패했습니다.\n\n{exc}"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "KOBIS API가 JSON 형식의 응답을 보내지 않았습니다."
        ) from exc

    # 인증키가 틀린 경우에도 HTTP 상태코드는 200일 수 있으므로
    # faultInfo가 있는지 반드시 별도로 확인합니다.
    if "faultInfo" in data:
        fault_info = data["faultInfo"]

        # faultInfo 안의 메시지를 최대한 읽기 쉽게 표시합니다.
        if isinstance(fault_info, dict):
            message = (
                fault_info.get("message")
                or fault_info.get("messageText")
                or json.dumps(fault_info, ensure_ascii=False)
            )
        else:
            message = str(fault_info)

        raise RuntimeError(
            f"KOBIS API에서 오류를 반환했습니다.\n\n{message}"
        )

    boxoffice_result = data.get("boxOfficeResult")

    if not boxoffice_result:
        raise RuntimeError(
            "KOBIS 응답에 boxOfficeResult가 없습니다. "
            "API 응답 형식이나 조회 날짜를 확인하세요."
        )

    movie_list = boxoffice_result.get("dailyBoxOfficeList", [])

    if not movie_list:
        raise RuntimeError(
            "조회된 영화 목록이 없습니다. "
            "조회 날짜가 올바른지, KOBIS에서 해당 날짜의 "
            "일일 박스오피스가 집계되었는지 확인하세요."
        )

    return movie_list


# -----------------------------
# 숫자 변환
# -----------------------------

def to_int(value):
    """문자열로 온 숫자를 정수로 변환합니다."""
    try:
        return int(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0


def make_dataframe(movie_list):
    """KOBIS 응답을 화면에 표시하기 좋은 데이터프레임으로 만듭니다."""
    rows = []

    for movie in movie_list:
        rows.append(
            {
                "순위": to_int(movie.get("rank")),
                "영화명": movie.get("movieNm", ""),
                "개봉일": movie.get("openDt", ""),
                "관객수": to_int(movie.get("audiCnt")),
                "누적관객": to_int(movie.get("audiAcc")),
                "스크린수": to_int(movie.get("scrnCnt")),
            }
        )

    df = pd.DataFrame(rows)

    # 혹시 API가 순서대로 보내지 않더라도 순위순으로 정렬합니다.
    df = df.sort_values("순위").reset_index(drop=True)

    return df


# -----------------------------
# 화면
# -----------------------------

st.title("🎬 어제의 박스오피스")

target_dt = get_yesterday_kst()
display_date = datetime.strptime(target_dt, "%Y%m%d").strftime("%Y-%m-%d")

st.caption(f"KOBIS 일일 박스오피스 · 조회일: {display_date}")

try:
    movie_list = get_boxoffice(target_dt)
    df = make_dataframe(movie_list)

except Exception as exc:
    # 오류가 발생해도 빈 화면으로 끝내지 않고
    # 사용자가 확인할 내용을 안내합니다.
    st.error("박스오피스 데이터를 가져오지 못했습니다.")

    st.markdown(
        """
        ### 확인해 주세요

        - Streamlit Cloud의 **Settings → Secrets**에
          `KOBIS_KEY`가 등록되어 있는지 확인하세요.
        - `KOBIS_KEY`에 KOBIS Open API에서 발급받은 인증키를
          정확히 입력했는지 확인하세요.
        - KOBIS에서 어제 날짜의 **일일 박스오피스가 집계되었는지**
          확인하세요.
        - 잠시 후 다시 접속하거나 페이지를 새로고침해 보세요.
        - 아래는 API에서 반환된 오류 내용입니다.
        """
    )

    st.code(str(exc))
    st.stop()


# 영화 목록이 만들어졌는지 마지막으로 확인합니다.
if df.empty:
    st.error(
        "영화 목록이 비어 있습니다. "
        "KOBIS에서 해당 날짜의 박스오피스 집계 여부와 "
        "KOBIS_KEY 설정을 확인하세요."
    )
    st.stop()


# -----------------------------
# 1위 영화
# -----------------------------

first_movie = df.iloc[0]

st.subheader("🥇 1위 영화")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "영화",
        first_movie["영화명"],
    )

with col2:
    st.metric(
        "당일 관객수",
        f"{first_movie['관객수']:,}명",
    )

with col3:
    st.metric(
        "누적 관객수",
        f"{first_movie['누적관객']:,}명",
    )


# -----------------------------
# 관객수 상위 5편 막대그래프
# -----------------------------

st.subheader("📊 관객수 상위 5편")

top5 = (
    df.sort_values("관객수", ascending=False)
    .head(5)
    .set_index("영화명")[["관객수"]]
)

st.bar_chart(top5)


# -----------------------------
# 전체 박스오피스 표
# -----------------------------

st.subheader("🎞️ 전체 박스오피스")

# 숫자 컬럼은 실제 숫자 타입으로 유지합니다.
# format을 사용하면 화면에서는 천 단위 쉼표를 보여줄 수 있습니다.
st.dataframe(
    df.style.format(
        {
            "순위": "{:,.0f}",
            "관객수": "{:,.0f}",
            "누적관객": "{:,.0f}",
            "스크린수": "{:,.0f}",
        }
    ),
    use_container_width=True,
    hide_index=True,
)
