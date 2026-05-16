"""UI 모듈 테스트 — APIClient, session_state, 컴포넌트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

# ──────────────────────────────────────────────
# APIClient
# ──────────────────────────────────────────────


class TestAPIClient:
    def _make_client(self, api_key: str = ""):
        from src.ui.utils.api_client import APIClient

        return APIClient(base_url="http://test:8000", api_key=api_key)

    def test_api_key_header_set(self) -> None:
        client = self._make_client(api_key="secret-key")
        assert client._client.headers["X-API-Key"] == "secret-key"

    def test_api_key_header_absent_when_empty(self) -> None:
        client = self._make_client(api_key="")
        assert "X-API-Key" not in client._client.headers

    @patch.object(httpx.Client, "get")
    def test_health_success(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "faiss_loaded": True}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        result = client.health()
        assert result == {"status": "ok", "faiss_loaded": True}
        mock_get.assert_called_once_with("/health", params=None)

    @patch.object(httpx.Client, "get")
    def test_health_failure_returns_none(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = httpx.ConnectError("refused")
        client = self._make_client()
        assert client.health() is None

    @patch.object(httpx.Client, "get")
    def test_get_models(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": [], "default_model": "gpt-4o-mini"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        result = client.get_models()
        assert result["default_model"] == "gpt-4o-mini"

    @patch.object(httpx.Client, "post")
    def test_generate(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"answer": "답변", "sources": []}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.generate("질문", model="gpt-4o-mini")
        assert result["answer"] == "답변"

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["query"] == "질문"
        assert payload["model"] == "gpt-4o-mini"

    @patch.object(httpx.Client, "post")
    def test_search(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [], "total": 0}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.search("질문", strategy="vector_only", top_k=3)
        assert result["total"] == 0

    @patch.object(httpx.Client, "get")
    def test_get_policies(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"policies": [], "total": 0, "page": 1, "limit": 12}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        result = client.get_policies(category="housing", page=2, limit=6)
        assert result is not None
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["category"] == "housing"
        assert params["page"] == 2

    @patch.object(httpx.Client, "post")
    def test_generate_failure_returns_none(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = httpx.HTTPStatusError("429", request=MagicMock(), response=MagicMock(status_code=429))
        client = self._make_client()
        assert client.generate("질문") is None

    @patch.object(httpx.Client, "post")
    def test_evaluate(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [], "total": 0, "evaluated": 0, "errors": 0}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = self._make_client()
        samples = [{"id": "q1", "question": "q", "answer": "a", "ground_truth": "g", "contexts": ["c"]}]
        result = client.evaluate(samples=samples)
        assert result["total"] == 0


# ──────────────────────────────────────────────
# Session State
# ──────────────────────────────────────────────


class TestSessionState:
    @patch("streamlit.session_state", new_callable=dict)
    def test_init_state_sets_defaults(self, mock_state: dict) -> None:
        from src.ui.utils.session_state import KEY_MESSAGES, KEY_STRATEGY, KEY_TOP_K, init_state

        init_state()

        assert mock_state[KEY_MESSAGES] == []
        assert mock_state[KEY_STRATEGY] == "hybrid"
        assert mock_state[KEY_TOP_K] == 5

    @patch("streamlit.session_state", new_callable=dict)
    def test_init_state_preserves_existing(self, mock_state: dict) -> None:
        from src.ui.utils.session_state import KEY_STRATEGY, init_state

        mock_state[KEY_STRATEGY] = "vector_only"
        init_state()
        assert mock_state[KEY_STRATEGY] == "vector_only"

    @patch("streamlit.session_state", new_callable=dict)
    def test_messages_are_independent_lists(self, mock_state: dict) -> None:
        from src.ui.utils.session_state import KEY_MESSAGES, init_state

        init_state()
        mock_state[KEY_MESSAGES].append({"role": "user", "content": "hi"})

        mock_state2: dict = {}
        with patch("streamlit.session_state", mock_state2):
            init_state()
        assert mock_state2[KEY_MESSAGES] == []


# ──────────────────────────────────────────────
# Style
# ──────────────────────────────────────────────


class TestStyle:
    def test_category_colors_complete(self) -> None:
        from src.ui.utils.style import CATEGORY_COLORS, CATEGORY_LABELS

        assert set(CATEGORY_COLORS.keys()) == set(CATEGORY_LABELS.keys())

    def test_custom_css_is_html(self) -> None:
        from src.ui.utils.style import CUSTOM_CSS

        assert "<style>" in CUSTOM_CSS
        assert "</style>" in CUSTOM_CSS


# ──────────────────────────────────────────────
# Components (함수 단위)
# ──────────────────────────────────────────────


class TestPolicyCardHelpers:
    def test_category_tag_html_known(self) -> None:
        from src.ui.components.policy_card import _category_tag_html

        html = _category_tag_html("housing")
        assert "주거" in html
        assert "category-tag" in html
        assert "color:" in html

    def test_category_tag_html_unknown(self) -> None:
        from src.ui.components.policy_card import _category_tag_html

        html = _category_tag_html("unknown_cat")
        assert "unknown_cat" in html
        assert "category-tag" in html

    def test_category_tag_html_empty(self) -> None:
        from src.ui.components.policy_card import _category_tag_html

        html = _category_tag_html("")
        assert "기타" in html


class TestMetricsDisplayHelpers:
    def test_render_metrics_table_empty(self) -> None:
        from src.ui.components.metrics_display import render_metrics_table

        with patch("streamlit.dataframe") as mock_df:
            render_metrics_table([])
            mock_df.assert_not_called()

    def test_render_metrics_table_with_data(self) -> None:
        from src.ui.components.metrics_display import render_metrics_table

        items = [
            {
                "id": "q1",
                "ragas": {
                    "faithfulness": 0.8,
                    "answer_relevancy": 0.9,
                    "context_precision": 0.7,
                    "context_recall": 0.85,
                },
                "judge": {"average": 0.75},
                "safety": {"hallucination_score": 0.1},
            }
        ]
        with patch("streamlit.dataframe") as mock_df:
            render_metrics_table(items)
            mock_df.assert_called_once()
            rows = mock_df.call_args[0][0]
            assert len(rows) == 1
            assert rows[0]["ID"] == "q1"
            assert rows[0]["Faithfulness"] == 0.8
