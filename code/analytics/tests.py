from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase


# =============================================================================
# Helper: buat mock collection
# =============================================================================

def _make_mock_col(inserted_id="abc123"):
    col = MagicMock()
    insert_result = MagicMock()
    insert_result.inserted_id = inserted_id
    col.insert_one.return_value = insert_result

    insert_many_result = MagicMock()
    insert_many_result.inserted_ids = ["id1", "id2"]
    col.insert_many.return_value = insert_many_result

    update_result = MagicMock()
    update_result.modified_count = 1
    col.update_one.return_value = update_result
    col.update_many.return_value = update_result

    delete_result = MagicMock()
    delete_result.deleted_count = 1
    col.delete_one.return_value = delete_result
    col.delete_many.return_value = delete_result

    col.count_documents.return_value = 5
    col.find_one.return_value = {
        "_id": "507f1f77bcf86cd799439011",
        "user_id": 1,
        "action": "view_course",
    }

    # find() returns iterable
    col.find.return_value = iter([
        {"_id": "507f1f77bcf86cd799439011", "user_id": 1, "action": "view_course"},
    ])

    col.aggregate.return_value = iter([])
    return col


# =============================================================================
# Test: build_activity_log (document schema — embedding)
# =============================================================================

class TestBuildActivityLog(TestCase):
    def test_structure_lengkap(self):
        from analytics.mongo_service import build_activity_log
        doc = build_activity_log(
            user_id=1,
            action="view_course",
            course_name="Django Basics",
            metadata={"ip": "127.0.0.1", "browser": "Chrome"},
        )
        self.assertEqual(doc["user_id"], 1)
        self.assertEqual(doc["action"], "view_course")
        self.assertEqual(doc["course_name"], "Django Basics")
        self.assertIn("timestamp", doc)
        self.assertIsInstance(doc["timestamp"], datetime)
        self.assertEqual(doc["metadata"]["ip"], "127.0.0.1")

    def test_tanpa_metadata(self):
        from analytics.mongo_service import build_activity_log
        doc = build_activity_log(user_id=None, action="register")
        self.assertEqual(doc["metadata"], {})
        self.assertIsNone(doc["user_id"])


# =============================================================================
# Test: build_course_progress (document schema — referencing)
# =============================================================================

class TestBuildCourseProgress(TestCase):
    def test_structure_referencing(self):
        from analytics.mongo_service import build_course_progress
        doc = build_course_progress(
            user_id=1,
            course_id=101,
            completed_contents=[1, 3, 5],
            progress_percentage=60.0,
            quiz_scores=[{"quiz_id": 1, "score": 85, "attempt": 1}],
        )
        # user_id & course_id adalah referensi ke PostgreSQL
        self.assertEqual(doc["user_id"], 1)
        self.assertEqual(doc["course_id"], 101)
        self.assertEqual(doc["progress_percentage"], 60.0)
        self.assertEqual(len(doc["completed_contents"]), 3)
        self.assertEqual(doc["quiz_scores"][0]["score"], 85)
        self.assertIn("last_accessed", doc)

    def test_default_kosong(self):
        from analytics.mongo_service import build_course_progress
        doc = build_course_progress(user_id=2, course_id=200)
        self.assertEqual(doc["completed_contents"], [])
        self.assertEqual(doc["quiz_scores"], [])
        self.assertEqual(doc["progress_percentage"], 0.0)


# =============================================================================
# Test: log_activity (CRUD — insert)
# =============================================================================

class TestLogActivity(TestCase):
    @patch("analytics.mongo_service.get_analytics_db")
    def test_log_activity_berhasil(self, mock_get_db):
        from analytics.mongo_service import log_activity

        mock_col = _make_mock_col(inserted_id="507f1f77bcf86cd799439011")
        mock_get_db.return_value.activity_logs = mock_col

        log_id = log_activity(user_id=1, action="view_course", course_name="Django Basics")

        # Verifikasi insert_one dipanggil
        mock_col.insert_one.assert_called_once()
        # Return value harus berupa string
        self.assertIsInstance(log_id, str)

    @patch("analytics.mongo_service.get_analytics_db")
    def test_log_activity_anonymous(self, mock_get_db):
        from analytics.mongo_service import log_activity

        mock_col = _make_mock_col()
        mock_get_db.return_value.activity_logs = mock_col

        log_activity(user_id=None, action="view_course")
        call_args = mock_col.insert_one.call_args[0][0]
        self.assertIsNone(call_args["user_id"])


# =============================================================================
# Test: CRUD — find, count, update, delete
# =============================================================================

class TestCRUDOperations(TestCase):
    @patch("analytics.mongo_service.get_analytics_db")
    def test_count_activity_logs(self, mock_get_db):
        from analytics.mongo_service import count_activity_logs

        mock_col = _make_mock_col()
        mock_get_db.return_value.activity_logs = mock_col

        count = count_activity_logs({"action": "view_course"})
        mock_col.count_documents.assert_called_once_with({"action": "view_course"})
        self.assertEqual(count, 5)

    @patch("analytics.mongo_service.get_analytics_db")
    def test_update_activity_log(self, mock_get_db):
        from analytics.mongo_service import update_activity_log
        from bson import ObjectId

        mock_col = _make_mock_col()
        mock_get_db.return_value.activity_logs = mock_col

        valid_id = "507f1f77bcf86cd799439011"
        result = update_activity_log(valid_id, {"reviewed": True})
        self.assertTrue(result)

    @patch("analytics.mongo_service.get_analytics_db")
    def test_delete_activity_log(self, mock_get_db):
        from analytics.mongo_service import delete_activity_log

        mock_col = _make_mock_col()
        mock_get_db.return_value.activity_logs = mock_col

        valid_id = "507f1f77bcf86cd799439011"
        result = delete_activity_log(valid_id)
        self.assertTrue(result)
        mock_col.delete_one.assert_called_once()

    @patch("analytics.mongo_service.get_analytics_db")
    def test_upsert_user_action(self, mock_get_db):
        from analytics.mongo_service import upsert_user_action

        mock_col = _make_mock_col()
        mock_get_db.return_value.activity_logs = mock_col

        result = upsert_user_action(user_id=1, action="daily_login")
        self.assertTrue(result)
        # Pastikan dipanggil dengan upsert=True
        call_kwargs = mock_col.update_one.call_args[1]
        self.assertTrue(call_kwargs.get("upsert"))


# =============================================================================
# Test: Aggregation Pipelines
# =============================================================================

class TestAggregationPipelines(TestCase):
    @patch("analytics.mongo_service.get_analytics_db")
    def test_get_popular_courses(self, mock_get_db):
        from analytics.mongo_service import get_popular_courses

        mock_col = MagicMock()
        mock_col.aggregate.return_value = iter([
            {"course_name": "Django Basics", "total_views": 150},
            {"course_name": "Python OOP", "total_views": 90},
        ])
        mock_get_db.return_value.activity_logs = mock_col

        result = get_popular_courses(limit=5)

        mock_col.aggregate.assert_called_once()
        # Pipeline harus dimulai dengan $match action=view_course
        pipeline = mock_col.aggregate.call_args[0][0]
        self.assertEqual(pipeline[0]["$match"]["action"], "view_course")
        self.assertEqual(len(result), 2)

    @patch("analytics.mongo_service.get_analytics_db")
    def test_get_user_activity_summary(self, mock_get_db):
        from analytics.mongo_service import get_user_activity_summary

        mock_col = MagicMock()
        mock_col.aggregate.return_value = iter([
            {"action": "view_course", "count": 10, "last_activity": datetime.now(timezone.utc)},
        ])
        mock_get_db.return_value.activity_logs = mock_col

        result = get_user_activity_summary(user_id=1)

        pipeline = mock_col.aggregate.call_args[0][0]
        # Stage pertama harus $match user_id=1
        self.assertEqual(pipeline[0]["$match"]["user_id"], 1)
        self.assertEqual(len(result), 1)

    @patch("analytics.mongo_service.get_analytics_db")
    def test_get_daily_activity_summary(self, mock_get_db):
        from analytics.mongo_service import get_daily_activity_summary

        mock_col = MagicMock()
        mock_col.aggregate.return_value = iter([
            {"date": "2024-01-15", "total_activities": 50, "unique_users_count": 12},
        ])
        mock_get_db.return_value.activity_logs = mock_col

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 31, tzinfo=timezone.utc)
        result = get_daily_activity_summary(start, end)

        pipeline = mock_col.aggregate.call_args[0][0]
        # Stage pertama harus $match timestamp dengan $gte dan $lte
        match_stage = pipeline[0]["$match"]["timestamp"]
        self.assertIn("$gte", match_stage)
        self.assertIn("$lte", match_stage)
        self.assertEqual(len(result), 1)


# =============================================================================
# Test: ensure_indexes
# =============================================================================

class TestEnsureIndexes(TestCase):
    @patch("analytics.mongo_service.get_analytics_db")
    def test_indexes_dibuat(self, mock_get_db):
        from analytics.mongo_service import ensure_indexes

        mock_col = MagicMock()
        mock_get_db.return_value.activity_logs = mock_col

        ensure_indexes()

        # Minimal 5 index yang harus dibuat
        self.assertGreaterEqual(mock_col.create_index.call_count, 5)

    @patch("analytics.mongo_service.get_analytics_db")
    def test_indexes_gagal_tidak_crash(self, mock_get_db):
        from pymongo.errors import ConnectionFailure
        from analytics.mongo_service import ensure_indexes

        mock_col = MagicMock()
        mock_col.create_index.side_effect = ConnectionFailure("timeout")
        mock_get_db.return_value.activity_logs = mock_col

        # Harus tidak raise exception
        try:
            ensure_indexes()
        except Exception:
            self.fail("ensure_indexes() raised exception padahal seharusnya tidak")
