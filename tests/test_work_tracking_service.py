import unittest
from datetime import date, datetime, timezone
from uuid import uuid4

from app.db.models import WorkActivity, WorkItem, WorkItemStatus
from app.services.work_tracking.models import WorkActivityCreate, WorkItemCreate, WorkItemUpdate
from app.services.work_tracking.service import WorkTrackingService


class FakeWorkItemRepository:
    def __init__(self) -> None:
        self.items: dict[str, WorkItem] = {}

    async def get(self, item_id: str):
        return self.items.get(item_id)

    async def list(self, **kwargs):
        return list(self.items.values())

    def add(self, item: WorkItem) -> None:
        item.id = item.id or str(uuid4())
        item.created_at = item.created_at or datetime.now(timezone.utc)
        item.updated_at = item.updated_at or datetime.now(timezone.utc)
        item.activities = []
        self.items[item.id] = item

    def add_activity(self, activity: WorkActivity) -> None:
        activity.id = activity.id or str(uuid4())
        activity.created_at = activity.created_at or datetime.now(timezone.utc)
        self.items[activity.work_item_id].activities.append(activity)

    async def flush(self) -> None:
        return None

    async def refresh(self, instance: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class WorkTrackingServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = FakeWorkItemRepository()
        self.service = WorkTrackingService(self.repository)  # type: ignore[arg-type]

    async def test_completed_item_gets_completion_timestamp(self) -> None:
        item = await self.service.create(
            WorkItemCreate(title="API 개발", status=WorkItemStatus.COMPLETED)
        )

        self.assertEqual(item.status, WorkItemStatus.COMPLETED)
        self.assertIsNotNone(item.completed_at)

    async def test_moving_back_to_in_progress_clears_completion_timestamp(self) -> None:
        item = await self.service.create(
            WorkItemCreate(title="API 개발", status=WorkItemStatus.COMPLETED)
        )

        updated = await self.service.update(
            item.id,
            WorkItemUpdate(status=WorkItemStatus.IN_PROGRESS),
        )

        self.assertEqual(updated.status, WorkItemStatus.IN_PROGRESS)
        self.assertIsNone(updated.completed_at)
        self.assertEqual(updated.activities[-1].status, WorkItemStatus.IN_PROGRESS)
        self.assertIn("상태 변경", updated.activities[-1].content)

    async def test_activity_can_update_item_status(self) -> None:
        item = await self.service.create(WorkItemCreate(title="테스트"))

        activity = await self.service.add_activity(
            item.id,
            WorkActivityCreate(
                activity_date=date(2026, 8, 18),
                content="테스트 완료",
                status=WorkItemStatus.COMPLETED,
            ),
        )

        self.assertEqual(activity.content, "테스트 완료")
        self.assertEqual(item.status, WorkItemStatus.COMPLETED)
        self.assertIsNotNone(item.completed_at)

    async def test_result_change_is_recorded_as_activity(self) -> None:
        item = await self.service.create(
            WorkItemCreate(title="집계 서비스", status=WorkItemStatus.IN_PROGRESS)
        )

        updated = await self.service.update(
            item.id,
            WorkItemUpdate(result="분류 규칙 구현 완료"),
        )

        self.assertEqual(updated.activities[-1].content, "분류 규칙 구현 완료")
        self.assertEqual(updated.activities[-1].status, WorkItemStatus.IN_PROGRESS)

    def test_update_rejects_null_for_required_database_fields(self) -> None:
        with self.assertRaises(ValueError):
            WorkItemUpdate(status=None)
        with self.assertRaises(ValueError):
            WorkItemUpdate(title=None)


if __name__ == "__main__":
    unittest.main()
