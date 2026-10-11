import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.main import app
from app.models.models import App, VerificationCheck
from app.services.taxonomy import seed_taxonomy, seed_catalog
from app.services.verification import check_website_availability, derive_verification_status
from datetime import datetime

# Setup test in-memory database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    seed_taxonomy(db)
    seed_catalog(db)
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"


def test_ten_seed_apps_exist(db):
    apps = db.query(App).all()
    assert len(apps) >= 10
    slugs = {a.slug for a in apps}
    expected = {"audacity", "vlc", "obs-studio", "gimp", "bleachbit", "kopia", "czkawka", "immich", "kodi", "7-zip"}
    assert expected.issubset(slugs)


def test_search_database_backed_music(client):
    response = client.get("/api/v1/search?q=music")
    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] > 0
    slugs = [r["slug"] for r in data["results"]]
    assert "audacity" in slugs or "vlc" in slugs


def test_search_database_backed_storage_clean(client):
    response = client.get("/api/v1/search?q=clean+disk")
    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] > 0
    slugs = [r["slug"] for r in data["results"]]
    assert "bleachbit" in slugs or "czkawka" in slugs


def test_app_detail_and_stored_verification(client):
    response = client.get("/api/v1/apps/audacity")
    assert response.status_code == 200
    data = response.json()
    assert data["slug"] == "audacity"
    assert data["name"] == "Audacity"
    assert data["homepage_url"] == "https://www.audacityteam.org/"
    assert data["license_state"] == "confirmed_open_source"
    assert len(data["capabilities"]) > 0
    assert len(data["releases"]) > 0

    # Verification summary must exist and come from database
    v_summary = data["verification_summary"]
    assert v_summary["overall_status"] in ["VERIFIED_RECENTLY", "PARTIALLY_VERIFIED"]
    assert v_summary["website_check"] is not None
    assert v_summary["website_check"]["check_type"] == "website_availability"
    assert v_summary["website_check"]["status"] == "SUCCESS"
    assert v_summary["website_check"]["checked_at"] is not None


def test_failed_check_produces_honest_failure_state(db, client):
    # Create or update an app with a failed check
    app = db.query(App).filter(App.slug == "audacity").first()
    failed_check = VerificationCheck(
        app_id=app.id,
        check_type="website_availability",
        status="FAILED",
        duration_ms=45,
        checked_at=datetime.utcnow(),
        http_status=503,
        final_url="https://broken-service.invalid",
        tls_valid=False,
        error_message="HTTP status 503 Service Unavailable"
    )
    db.add(failed_check)
    db.commit()

    checks = db.query(VerificationCheck).filter(VerificationCheck.app_id == app.id).all()
    derived = derive_verification_status(checks)
    assert derived == "VERIFICATION_FAILED"

    # API response reflects honest failure state
    resp = client.get("/api/v1/apps/audacity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["verification_summary"]["overall_status"] == "VERIFICATION_FAILED"


def test_database_record_modification_reflects_dynamically(db, client):
    # Changing the underlying database record must change the displayed information without frontend edit
    app = db.query(App).filter(App.slug == "bleachbit").first()
    original_summary = app.summary
    app.summary = "Dynamically modified summary for BleachBit testing"
    db.commit()

    resp = client.get("/api/v1/apps/bleachbit")
    assert resp.status_code == 200
    assert resp.json()["summary"] == "Dynamically modified summary for BleachBit testing"

    # Restore
    app.summary = original_summary
    db.commit()


def test_unknown_query_produces_no_fabricated_results(client):
    resp = client.get("/api/v1/search?q=quantum+teleportation+reactor+superconductor")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_results"] == 0
    assert data["results"] == []
    # Suggest categories instead
    assert len(data["suggested_categories"]) > 0


def test_real_website_check_execution():
    # Test real network execution against a reliable public endpoint (e.g. python.org or example.com)
    result = check_website_availability("https://www.example.com", timeout_sec=5.0)
    assert result["status"] in ["SUCCESS", "FAILED"]
    assert "duration_ms" in result
    assert result["final_url"] is not None


def test_ssrf_prohibited_destinations_blocked():
    # Localhost / loopback must be rejected immediately without making network calls
    result = check_website_availability("http://127.0.0.1:8080/admin")
    assert result["status"] == "FAILED"
    assert "Prohibited IP" in result["error_message"]
    assert result["tls_valid"] is False

    result2 = check_website_availability("http://169.254.169.254/latest/meta-data")
    assert result2["status"] == "FAILED"
    assert "Prohibited IP" in result2["error_message"]
