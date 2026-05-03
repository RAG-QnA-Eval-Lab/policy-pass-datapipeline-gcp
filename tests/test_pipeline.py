"""파이프라인 + MongoDB 클라이언트 테스트."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.ingestion.pipeline import (
    build_index_from_directory,
    build_index_from_policies,
    save_policies_json,
)


class TestSavePoliciesJson:
    def test_saves_json(self, tmp_path: Path) -> None:
        policies = [{"policy_id": "P1", "title": "정책1"}, {"policy_id": "P2", "title": "정책2"}]
        output = tmp_path / "out.json"

        result = save_policies_json(policies, output)

        assert result == output
        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["policy_id"] == "P1"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        output = tmp_path / "nested" / "dir" / "out.json"
        save_policies_json([{"id": 1}], output)
        assert output.exists()

    def test_empty_list(self, tmp_path: Path) -> None:
        output = tmp_path / "empty.json"
        save_policies_json([], output)
        assert json.loads(output.read_text(encoding="utf-8")) == []


class TestBuildIndexFromDirectory:
    @patch("src.ingestion.pipeline.embed_texts")
    def test_builds_index(self, mock_embed: MagicMock, tmp_path: Path) -> None:
        policy = {
            "policy_id": "P1",
            "title": "테스트",
            "raw_content": "정책명: 테스트\n요약: 테스트 정책 내용",
            "source_name": "test",
            "category": "housing",
        }
        (tmp_path / "input").mkdir()
        (tmp_path / "input" / "test.json").write_text(
            json.dumps([policy], ensure_ascii=False), encoding="utf-8"
        )

        mock_embed.return_value = [[0.1] * 128]
        output_dir = tmp_path / "output"

        result = build_index_from_directory(tmp_path / "input", output_dir)

        assert result["index_built"] is True
        assert result["documents"] == 1
        assert result["chunks"] >= 1
        assert (output_dir / "faiss.index").exists()
        assert (output_dir / "metadata.json").exists()

    def test_empty_directory(self, tmp_path: Path) -> None:
        (tmp_path / "input").mkdir()
        result = build_index_from_directory(tmp_path / "input", tmp_path / "output")

        assert result["index_built"] is False
        assert result["documents"] == 0

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        result = build_index_from_directory(tmp_path / "nope", tmp_path / "output")

        assert result["index_built"] is False
        assert result["documents"] == 0


class TestBuildIndexFromPolicies:
    @patch("src.ingestion.pipeline.embed_texts")
    def test_builds_from_policy_dicts(self, mock_embed: MagicMock, tmp_path: Path) -> None:
        policies = [
            {"policy_id": "P1", "title": "정책1", "raw_content": "내용1", "source_name": "test"},
            {"policy_id": "P2", "title": "정책2", "raw_content": "내용2", "source_name": "test"},
        ]
        mock_embed.return_value = [[0.1] * 128, [0.2] * 128]

        result = build_index_from_policies(policies, tmp_path / "index")

        assert result["index_built"] is True
        assert result["documents"] == 2

    @patch("src.ingestion.pipeline.embed_texts")
    def test_metadata_in_json(self, mock_embed: MagicMock, tmp_path: Path) -> None:
        policies = [
            {"policy_id": "P1", "title": "정책1", "raw_content": "내용1", "source_name": "test", "category": "housing"},
        ]
        mock_embed.return_value = [[0.5] * 128]

        build_index_from_policies(policies, tmp_path / "index")

        with open(tmp_path / "index" / "metadata.json", encoding="utf-8") as f:
            metadata = json.load(f)

        assert len(metadata) == 1
        assert metadata[0]["policy_id"] == "P1"
        assert metadata[0]["category"] == "housing"

    def test_empty_policies(self, tmp_path: Path) -> None:
        result = build_index_from_policies([], tmp_path / "index")
        assert result["index_built"] is False

    def test_skips_empty_content(self, tmp_path: Path) -> None:
        policies = [{"policy_id": "P1", "raw_content": "", "source_name": "test"}]
        result = build_index_from_policies(policies, tmp_path / "index")
        assert result["documents"] == 0


class TestMongoClient:
    def test_upsert_policy(self) -> None:
        from src.ingestion.mongo_client import PolicyMetadataStore

        store = PolicyMetadataStore()
        mock_collection = MagicMock()
        store._client = MagicMock()

        with patch.object(type(store), "policies", new_callable=lambda: property(lambda self: mock_collection)):
            store.upsert_policy({"policy_id": "P1", "title": "테스트"})

        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"policy_id": "P1"}
        assert call_args[1]["upsert"] is True

    def test_upsert_policy_no_id_skipped(self) -> None:
        from src.ingestion.mongo_client import PolicyMetadataStore

        store = PolicyMetadataStore()
        mock_collection = MagicMock()
        store._client = MagicMock()

        with patch.object(type(store), "policies", new_callable=lambda: property(lambda self: mock_collection)):
            store.upsert_policy({"title": "ID 없음"})

        mock_collection.update_one.assert_not_called()

    def test_upsert_policies_batch_bulk_write(self) -> None:
        from src.ingestion.mongo_client import PolicyMetadataStore

        store = PolicyMetadataStore()
        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.upserted_count = 2
        mock_result.modified_count = 1
        mock_collection.bulk_write.return_value = mock_result
        store._client = MagicMock()

        with patch.object(type(store), "policies", new_callable=lambda: property(lambda self: mock_collection)):
            count = store.upsert_policies_batch([
                {"policy_id": "P1", "title": "정책1"},
                {"policy_id": "P2", "title": "정책2"},
                {"policy_id": "P3", "title": "정책3"},
            ])

        mock_collection.bulk_write.assert_called_once()
        assert count == 3

    def test_upsert_gcs_assets_batch_bulk_write(self) -> None:
        from src.ingestion.mongo_client import PolicyMetadataStore

        store = PolicyMetadataStore()
        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.upserted_count = 1
        mock_result.modified_count = 1
        mock_collection.bulk_write.return_value = mock_result
        store._client = MagicMock()

        with patch.object(type(store), "gcs_assets", new_callable=lambda: property(lambda self: mock_collection)):
            count = store.upsert_gcs_assets_batch([
                {"gcs_uri": "gs://bucket/eval/qa_pairs.json", "asset_type": "qa_dataset"},
                {"gcs_uri": "gs://bucket/index/faiss.index", "asset_type": "index_artifact"},
            ])

        mock_collection.bulk_write.assert_called_once()
        assert count == 2

    def test_upsert_qa_dataset(self) -> None:
        from src.ingestion.mongo_client import PolicyMetadataStore

        store = PolicyMetadataStore()
        mock_collection = MagicMock()
        store._client = MagicMock()

        with patch.object(type(store), "qa_datasets", new_callable=lambda: property(lambda self: mock_collection)):
            store.upsert_qa_dataset({"dataset_id": "youth_policy:1.0:test", "total_count": 100})

        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"dataset_id": "youth_policy:1.0:test"}
        assert call_args[1]["upsert"] is True

    def test_find_by_id(self) -> None:
        from src.ingestion.mongo_client import PolicyMetadataStore

        store = PolicyMetadataStore()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {"policy_id": "P1", "title": "테스트"}
        store._client = MagicMock()

        with patch.object(type(store), "policies", new_callable=lambda: property(lambda self: mock_collection)):
            result = store.find_by_id("P1")

        assert result["policy_id"] == "P1"
        mock_collection.find_one.assert_called_once_with({"policy_id": "P1"}, {"_id": 0})

    def test_log_ingestion(self) -> None:
        from src.ingestion.mongo_client import PolicyMetadataStore

        store = PolicyMetadataStore()
        mock_collection = MagicMock()
        store._client = MagicMock()

        with patch.object(
            type(store), "ingestion_logs", new_callable=lambda: property(lambda self: mock_collection)
        ):
            store.log_ingestion(source="data_portal", collected_count=100, valid_count=95)

        mock_collection.insert_one.assert_called_once()
        call_data = mock_collection.insert_one.call_args[0][0]
        assert call_data["source"] == "data_portal"
        assert call_data["collected_count"] == 100
        assert call_data["valid_count"] == 95

    def test_close(self) -> None:
        from src.ingestion.mongo_client import PolicyMetadataStore

        store = PolicyMetadataStore()
        mock_client = MagicMock()
        store._client = mock_client

        store.close()

        mock_client.close.assert_called_once()
        assert store._client is None
