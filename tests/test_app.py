"""
Tests for the Mergington High School Activities API.
"""

import copy
import pytest
from fastapi.testclient import TestClient
from src.app import app


def _get_activities_store():
    """
    Helper to access the underlying activities store.

    This indirection keeps tests resilient to changes in how the
    application stores activities (e.g., switching from an in-memory
    dict to another mechanism).
    """
    from src.app import activities  # Local import to avoid hard coupling at module level
    return activities


_activities_store = _get_activities_store()
# Store original activities for resetting between tests
_original_activities = copy.deepcopy(_activities_store)


@pytest.fixture(autouse=True)
def reset_activities():
    """Reset the in-memory activities database before each test."""
    # Restore original state
    _activities_store.clear()
    _activities_store.update(copy.deepcopy(_original_activities))
    yield
    # Cleanup after test
    _activities_store.clear()
    _activities_store.update(copy.deepcopy(_original_activities))


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


# ──────────────────────────────────────────────
# GET /activities
# ──────────────────────────────────────────────

class TestGetActivities:
    def test_returns_all_activities(self, client):
        response = client.get("/activities")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert len(data) == len(_original_activities)

    def test_activity_has_required_fields(self, client):
        response = client.get("/activities")
        data = response.json()
        for name, details in data.items():
            assert "description" in details
            assert "schedule" in details
            assert "max_participants" in details
            assert "participants" in details
            assert isinstance(details["participants"], list)

    def test_known_activity_exists(self, client):
        response = client.get("/activities")
        data = response.json()
        assert "Soccer Team" in data
        assert data["Soccer Team"]["max_participants"] == 22


# ──────────────────────────────────────────────
# GET / (redirect)
# ──────────────────────────────────────────────

class TestRoot:
    def test_root_redirects(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert "/static/index.html" in response.headers["location"]


# ──────────────────────────────────────────────
# POST /activities/{activity_name}/signup
# ──────────────────────────────────────────────

class TestSignup:
    def test_signup_success(self, client):
        response = client.post(
            "/activities/Soccer Team/signup?email=newstudent@mergington.edu"
        )
        assert response.status_code == 200
        assert "Signed up" in response.json()["message"]

    def test_signup_adds_participant(self, client):
        email = "newstudent@mergington.edu"
        client.post(f"/activities/Soccer Team/signup?email={email}")
        response = client.get("/activities")
        participants = response.json()["Soccer Team"]["participants"]
        assert email in participants

    def test_signup_duplicate_email(self, client):
        existing_email = "liam@mergington.edu"
        response = client.post(
            f"/activities/Soccer Team/signup?email={existing_email}"
        )
        assert response.status_code == 400
        assert "already signed up" in response.json()["detail"].lower()

    def test_signup_nonexistent_activity(self, client):
        response = client.post(
            "/activities/Nonexistent Activity/signup?email=test@mergington.edu"
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_signup_rejected_when_activity_full(self, client):
        # Fetch current activity state to determine capacity and current participants
        get_response = client.get("/activities")
        assert get_response.status_code == 200
        activity = get_response.json()["Soccer Team"]
        max_participants = activity["max_participants"]
        current_participants = list(activity["participants"])

        # Fill remaining slots with unique test emails
        remaining_slots = max_participants - len(current_participants)
        for i in range(remaining_slots):
            email = f"capacity_fill_{i}@mergington.edu"
            signup_response = client.post(
                f"/activities/Soccer Team/signup?email={email}"
            )
            assert signup_response.status_code == 200

        # Attempt one more signup beyond capacity and expect rejection
        overflow_email = "overflow_capacity@mergington.edu"
        overflow_response = client.post(
            f"/activities/Soccer Team/signup?email={overflow_email}"
        )
        assert overflow_response.status_code == 400
        detail = overflow_response.json().get("detail", "").lower()
        assert "full" in detail or "capacity" in detail
# ──────────────────────────────────────────────
# DELETE /activities/{activity_name}/unregister
# ──────────────────────────────────────────────

class TestUnregister:
    def test_unregister_success(self, client):
        response = client.delete(
            "/activities/Soccer Team/unregister?email=liam@mergington.edu"
        )
        assert response.status_code == 200
        assert "Unregistered" in response.json()["message"]

    def test_unregister_removes_participant(self, client):
        email = "liam@mergington.edu"
        client.delete(f"/activities/Soccer Team/unregister?email={email}")
        response = client.get("/activities")
        participants = response.json()["Soccer Team"]["participants"]
        assert email not in participants

    def test_unregister_not_signed_up(self, client):
        response = client.delete(
            "/activities/Soccer Team/unregister?email=nobody@mergington.edu"
        )
        assert response.status_code == 400
        assert "not signed up" in response.json()["detail"].lower()

    def test_unregister_nonexistent_activity(self, client):
        response = client.delete(
            "/activities/Nonexistent Activity/unregister?email=test@mergington.edu"
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# ──────────────────────────────────────────────
# Integration: signup then unregister
# ──────────────────────────────────────────────

class TestSignupUnregisterFlow:
    def test_signup_then_unregister(self, client):
        email = "flowtest@mergington.edu"
        activity = "Art Club"

        # Sign up
        res = client.post(f"/activities/{activity}/signup?email={email}")
        assert res.status_code == 200

        # Verify enrolled
        data = client.get("/activities").json()
        assert email in data[activity]["participants"]

        # Unregister
        res = client.delete(f"/activities/{activity}/unregister?email={email}")
        assert res.status_code == 200

        # Verify removed
        data = client.get("/activities").json()
        assert email not in data[activity]["participants"]

    def test_signup_respects_spot_count(self, client):
        """After signup, available spots should decrease by one."""
        data_before = client.get("/activities").json()
        activity = "Chess Club"
        before_count = len(data_before[activity]["participants"])

        client.post(f"/activities/{activity}/signup?email=spot@mergington.edu")

        data_after = client.get("/activities").json()
        after_count = len(data_after[activity]["participants"])
        assert after_count == before_count + 1
