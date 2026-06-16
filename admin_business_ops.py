import json
import logging
import shutil
from pathlib import Path

from auth_utils import normalize_email
from business_utils import get_business_by_key
from knowledge_utils import KNOWLEDGE_ROOT, get_business_upload_dir
from models import Business, BusinessSettings, KnowledgeEmbedding, KnowledgeFile, User

logger = logging.getLogger(__name__)

ROWE_ADMIN_EMAIL = "rowe-ai@outlook.com"
ROWE_WEBSITE_FOLDER = "rowe_ai_website"


def transfer_business_ownership(db, business_key: str, new_owner_email: str) -> dict:
    business = get_business_by_key(db, business_key)
    if not business:
        raise ValueError(f"Business not found: {business_key}")

    normalized_email = normalize_email(new_owner_email)
    new_owner = db.query(User).filter(User.email == normalized_email).first()
    if not new_owner:
        raise ValueError(f"User not found: {new_owner_email}")

    previous_owner_id = business.owner_id
    previous_owner = (
        db.query(User).filter(User.id == previous_owner_id).first()
        if previous_owner_id
        else None
    )

    business.owner_id = new_owner.id
    new_owner.business_id = business.id

    db.add(business)
    db.add(new_owner)
    db.commit()
    db.refresh(business)
    db.refresh(new_owner)

    return {
        "business_id": business.id,
        "folder_name": business.folder_name,
        "new_owner_id": new_owner.id,
        "new_owner_email": new_owner.email,
        "previous_owner_id": previous_owner_id,
        "previous_owner_email": previous_owner.email if previous_owner else None,
    }


def copy_business_settings(db, source_business: Business, target_business: Business) -> dict:
    if source_business.id == target_business.id:
        return {"updated": False}

    source = (
        db.query(BusinessSettings)
        .filter(BusinessSettings.business_id == source_business.id)
        .first()
    )
    if not source:
        return {"updated": False}

    target = (
        db.query(BusinessSettings)
        .filter(BusinessSettings.business_id == target_business.id)
        .first()
    )
    if not target:
        target = BusinessSettings(business_id=target_business.id)
        db.add(target)

    copied_fields = []

    def copy_if_empty(field_name: str):
        source_value = getattr(source, field_name)
        target_value = getattr(target, field_name)
        if source_value and not target_value:
            setattr(target, field_name, source_value)
            copied_fields.append(field_name)

    copy_if_empty("greeting_message")
    copy_if_empty("chatbot_tone")
    copy_if_empty("custom_instructions")
    copy_if_empty("faq_items")

    if source.max_response_length and (
        not target.max_response_length or target.max_response_length == 300
    ):
        target.max_response_length = source.max_response_length
        copied_fields.append("max_response_length")

    db.add(target)
    db.commit()

    return {"updated": bool(copied_fields), "fields": copied_fields}


def copy_legacy_knowledge_text(source_business: Business, target_business: Business) -> bool:
    source_path = KNOWLEDGE_ROOT / source_business.folder_name / "knowledge.txt"
    target_path = KNOWLEDGE_ROOT / target_business.folder_name / "knowledge.txt"

    if not source_path.exists() or not source_path.is_file():
        return False
    if target_path.exists() and target_path.read_text(encoding="utf-8", errors="ignore").strip():
        return False

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return True


def copy_knowledge_between_businesses(
    db,
    source_business: Business,
    target_business: Business,
    *,
    skip_existing: bool = True,
) -> dict:
    if source_business.id == target_business.id:
        return {"copied_files": 0, "skipped_files": 0, "copied_embeddings": 0}

    existing_names = {
        record.file_name
        for record in db.query(KnowledgeFile)
        .filter(KnowledgeFile.client_id == target_business.id)
        .all()
    }

    source_files = (
        db.query(KnowledgeFile)
        .filter(KnowledgeFile.client_id == source_business.id)
        .order_by(KnowledgeFile.id.asc())
        .all()
    )

    copied_files = 0
    skipped_files = 0
    copied_embeddings = 0
    upload_dir = get_business_upload_dir(target_business)

    for source_file in source_files:
        if skip_existing and source_file.file_name in existing_names:
            skipped_files += 1
            continue

        source_path = Path(source_file.file_path)
        if not source_path.exists() or not source_path.is_file():
            logger.warning(
                "Missing knowledge file on disk for file_id=%s path=%s",
                source_file.id,
                source_file.file_path,
            )
            continue

        destination_path = upload_dir / source_file.file_name
        if destination_path.exists():
            stem = destination_path.stem
            suffix = destination_path.suffix
            counter = 1
            while destination_path.exists():
                destination_path = upload_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        shutil.copy2(source_path, destination_path)

        new_file = KnowledgeFile(
            client_id=target_business.id,
            file_name=destination_path.name,
            file_path=str(destination_path),
            file_type=source_file.file_type,
            file_size=source_file.file_size,
        )
        db.add(new_file)
        db.flush()

        embeddings = (
            db.query(KnowledgeEmbedding)
            .filter(KnowledgeEmbedding.file_id == source_file.id)
            .all()
        )
        for embedding in embeddings:
            db.add(
                KnowledgeEmbedding(
                    client_id=target_business.id,
                    file_id=new_file.id,
                    chunk_text=embedding.chunk_text,
                    embedding_vector=embedding.embedding_vector,
                )
            )
            copied_embeddings += 1

        copied_files += 1
        existing_names.add(destination_path.name)

    legacy_copied = copy_legacy_knowledge_text(source_business, target_business)
    db.commit()

    return {
        "copied_files": copied_files,
        "skipped_files": skipped_files,
        "copied_embeddings": copied_embeddings,
        "legacy_knowledge_txt_copied": legacy_copied,
    }


def run_rowe_website_owner_migration(db) -> dict:
    website_business = get_business_by_key(db, ROWE_WEBSITE_FOLDER)
    if not website_business:
        raise ValueError(f"Business not found: {ROWE_WEBSITE_FOLDER}")

    previous_owner_id = website_business.owner_id
    previous_owner = (
        db.query(User).filter(User.id == previous_owner_id).first()
        if previous_owner_id
        else None
    )

    transfer_result = transfer_business_ownership(
        db,
        ROWE_WEBSITE_FOLDER,
        ROWE_ADMIN_EMAIL,
    )

    admin_owner = db.query(User).filter(User.email == ROWE_ADMIN_EMAIL).first()
    if admin_owner:
        admin_owner.billing_status = "active"
        admin_owner.subscription_active = 1
        db.add(admin_owner)
        db.commit()

    knowledge_summary = {
        "copied_files": 0,
        "skipped_files": 0,
        "copied_embeddings": 0,
        "legacy_knowledge_txt_copied": False,
        "sources": [],
    }
    settings_summary = {"updated": False, "fields": []}

    if previous_owner and previous_owner.id != transfer_result["new_owner_id"]:
        source_businesses = (
            db.query(Business)
            .filter(Business.owner_id == previous_owner.id)
            .all()
        )
        for source_business in source_businesses:
            if source_business.id == website_business.id:
                continue
            copy_result = copy_knowledge_between_businesses(
                db,
                source_business,
                website_business,
            )
            if any(
                copy_result[key]
                for key in (
                    "copied_files",
                    "copied_embeddings",
                    "legacy_knowledge_txt_copied",
                )
            ):
                knowledge_summary["sources"].append(source_business.folder_name)
            knowledge_summary["copied_files"] += copy_result["copied_files"]
            knowledge_summary["skipped_files"] += copy_result["skipped_files"]
            knowledge_summary["copied_embeddings"] += copy_result["copied_embeddings"]
            knowledge_summary["legacy_knowledge_txt_copied"] = (
                knowledge_summary["legacy_knowledge_txt_copied"]
                or copy_result["legacy_knowledge_txt_copied"]
            )

            settings_result = copy_business_settings(db, source_business, website_business)
            if settings_result.get("updated"):
                settings_summary["updated"] = True
                settings_summary["fields"].extend(settings_result.get("fields", []))

    website_business = get_business_by_key(db, ROWE_WEBSITE_FOLDER)
    file_count = (
        db.query(KnowledgeFile)
        .filter(KnowledgeFile.client_id == website_business.id)
        .count()
    )

    return {
        "message": "Rowe website ownership migration completed",
        "transfer": transfer_result,
        "knowledge": knowledge_summary,
        "settings": settings_summary,
        "website_knowledge_file_count": file_count,
    }
