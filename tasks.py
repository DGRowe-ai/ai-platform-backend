from datetime import datetime, timedelta, timezone
from database import SessionLocal
from models import Business
from email_utils import send_email
import logging

# Set up logging so you can see what happens
logger = logging.getLogger(__name__)

def send_inactivity_alerts():
    db = SessionLocal()
    
    try:
        # Calculate the cutoff date (7 days ago)
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        
        # Find all businesses that haven't been active in 7 days
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
                logger.info(f"Email sent to {biz.owner_email}")
            except Exception as e:
                # If one email fails, log it but keep going
                logger.error(f"Failed to send email to {biz.owner_email}: {str(e)}")
        
    except Exception as e:
        # If something major fails, log it
        logger.error(f"Error in send_inactivity_alerts: {str(e)}")
    
    finally:
        # ALWAYS close the database connection, even if something broke
        db.close()
        logger.info("Database connection closed")