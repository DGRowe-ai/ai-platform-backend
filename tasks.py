from datetime import datetime, timedelta, timezone
from database import SessionLocal
from models import Business
from email_utils import send_email
import logging

logger = logging.getLogger(__name__)

def send_inactivity_alerts():
    """Send inactivity reminder emails to businesses that haven't been used in 7 days"""
    db = SessionLocal()
    
    try:
        # Calculate cutoff date (7 days ago, UTC)
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        
        # Find all inactive businesses
        inactive = db.query(Business).filter(Business.last_active < cutoff).all()
        logger.info(f"Found {len(inactive)} inactive businesses")
        
        # Send email to each business
        for biz in inactive:
            try:
                send_email(
                    to_email=biz.owner_email,
                    subject="We Miss You!",
                    body="Your chatbot hasn't been used in a while. Log in to keep it active."
                )
                logger.info(f"Inactivity alert sent to {biz.owner_email}")
            except Exception as e:
                # Log individual email failures but continue with others
                logger.error(f"Failed to send email to {biz.owner_email}: {str(e)}")
        
        logger.info("Inactivity alert task completed")
        
    except Exception as e:
        logger.error(f"Error in send_inactivity_alerts: {str(e)}")
        
    finally:
        # Always close database connection, even if error occurred
        db.close()
        logger.info("Database connection closed")
