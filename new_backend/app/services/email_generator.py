from typing import Dict, Any, Optional, List
import json
import requests
from urllib.parse import urlparse
from openai import AzureOpenAI
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from sqlalchemy import or_

from app.models.models import GeneratedEmail, User, EmailTemplate

# Azure OpenAI Configuration
AZURE_OPENAI_API_KEY = "65f3a3cbcc54451d9ae6b8740303c648"
AZURE_OPENAI_ENDPOINT = "https://francecentral.api.cognitive.microsoft.com/"
AZURE_DEPLOYMENT_NAME = "Avocat"

class WebScraper:
    """Class for extracting information from company websites."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        })
    
    def extract_info(self, url: str) -> Dict[str, Any]:
        """Extract relevant information from a company website"""
        if not url or url.strip() == "":
            return {"success": False, "error": "No URL provided", "data": {}}
        
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            return {"success": False, "error": "Invalid URL", "data": {}}
        
        try:
            domain = url.split('://')[-1].split('/')[0]
            return {
                "success": True,
                "data": {
                    "about": f"Company with website {domain}",
                    "key_products": ["Product 1", "Product 2", "Service 1"],
                    "company_values": ["Innovation", "Quality", "Customer service"],
                    "recent_news": "No recent news available."
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e), "data": {}}

class EmailGenerator:
    def __init__(self, db: Session):
        self.db = db
        self.client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            api_version="2023-12-01-preview",
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )
        self.scraper = WebScraper()
    
    def extract_website_info(self, website_url: str) -> str:
        """Extract relevant information from a company website"""
        info = self.scraper.extract_info(website_url)
        
        if not info["success"]:
            return f"Failed to extract information: {info.get('error', 'Unknown error')}"
        
        data = info["data"]
        return f"""
        About: {data.get('about', 'Not available')}
        
        Key Products/Services: {', '.join(data.get('key_products', ['Not available']))}
        
        Company Values: {', '.join(data.get('company_values', ['Not available']))}
        
        Recent News: {data.get('recent_news', 'Not available')}
        """
    
    def generate_personalized_email(
        self,
        contact_data: Dict[str, Any],
        user: User,
        template: Optional[EmailTemplate] = None,
        stage: str = "outreach"
    ) -> GeneratedEmail:
        """Generate a personalized email using Azure OpenAI API"""
        
        # Extract information from company website
        website_info = self.extract_website_info(contact_data.get("Website", ""))
        
        # Build context for OpenAI API
        prompt = f"""
        Create a personalized outreach email in English for:
        
        First Name: {contact_data.get('First Name', '')}
        Last Name: {contact_data.get('Last Name', '')}
        Title: {contact_data.get('Title', '')}
        Company: {contact_data.get('Company', '')}
        Industry: {contact_data.get('Industry', '')}
        Keywords: {contact_data.get('Keywords', '')}
        SEO Description: {contact_data.get('SEO Description', '')}
        
        Company Information:
        {website_info}
        
        Sender Information:
        Name: [Your Name]
        Position: [Your Position]
        Company: [Your Company]
        Company Description: {user.company_description if user.company_description else "[brief description of company]"}
        
        Stage: {stage}
        
        Please generate a professional, personalized email that:
        1. References specific details about the recipient's company
        2. Demonstrates understanding of their industry
        3. Maintains a professional yet engaging tone
        4. Includes a clear call to action
        5. Is concise and to the point (aim for 3-4 short paragraphs maximum)
        6. If a company description is provided, use it to explain how your company's offerings align with the recipient's needs
        7. Avoid unnecessary details and keep the message focused on value proposition
        """
        
        try:
            response = self.client.chat.completions.create(
                model=AZURE_DEPLOYMENT_NAME,
                messages=[
                    {"role": "system", "content": "You are an expert email writer specializing in professional outreach. When a company description is provided, use it to explain how the sender's offerings align with the recipient's needs. Do not use any markdown formatting (like ** or *) in the email content."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1000
            )
            
            generated_content = response.choices[0].message.content
            
            # Extract subject from first line of content and remove "Subject: " prefix if present
            content_lines = generated_content.split('\n')
            subject = content_lines[0].strip()
            if subject.lower().startswith("subject: "):
                subject = subject[9:].strip()
            
            # Find the "Best regards" line and remove everything after it
            content = []
            for line in content_lines[1:]:
                if line.strip().lower() == "best regards,":
                    break
                content.append(line)
            
            # Join the content and add the correct signature
            content = '\n'.join(content).strip()
            
            # Remove any markdown formatting
            content = content.replace("**", "")
            
            # Replace placeholders with user information if available
            content = content.replace("[Your Name]", user.full_name if user.full_name else "[Your Name]")
            content = content.replace("[Your Position]", user.position if user.position else "[Your Position]")
            content = content.replace("[Your Company]", user.company_name if user.company_name else "[Your Company]")
            
            # Remove any existing signature lines after "Best regards" or similar phrases
            content_lines = content.split('\n')
            new_content = []
            signature_indicators = ["best regards", "sincerely", "kind regards", "warm regards", "looking forward", "thank you"]
            
            for line in content_lines:
                line_lower = line.strip().lower()
                if any(indicator in line_lower for indicator in signature_indicators):
                    break
                new_content.append(line)
            
            content = '\n'.join(new_content).strip()
            
            # Add consistent signature format
            signature = f"""
Best regards,
{user.full_name if user.full_name else "[Your Name]"}
{user.position if user.position else "[Your Position]"}
{user.company_name if user.company_name else "[Your Company]"}"""
            
            content = f"{content}\n\n{signature}"
            
            # Calculate follow-up dates based on stage
            now = datetime.utcnow()
            follow_up_date = None
            final_follow_up_date = None
            
            if stage == "outreach":
                follow_up_date = now + timedelta(days=3)  # First follow-up after 3 days
                final_follow_up_date = now + timedelta(days=7)  # Final follow-up after 7 days
            elif stage == "followup":
                follow_up_date = now + timedelta(days=2)  # Quick follow-up
                final_follow_up_date = now + timedelta(days=4)  # Final follow-up
            elif stage == "lastchance":
                follow_up_date = now + timedelta(days=1)  # Quick final follow-up
                final_follow_up_date = now + timedelta(days=2)  # Very final follow-up
            
            # Create and save the generated email
            email = GeneratedEmail(
                recipient_email=contact_data.get("Email", ""),
                recipient_name=f"{contact_data.get('First Name', '')} {contact_data.get('Last Name', '')}",
                recipient_company=contact_data.get("Company", ""),
                subject=subject,
                content=content,
                user_id=user.id,
                template_id=template.id if template else None,
                status="outreach_pending",
                stage=stage,
                follow_up_status="none",
                follow_up_date=follow_up_date,
                final_follow_up_date=final_follow_up_date,
                created_at=now,
                # Set legacy fields for backward compatibility
                to=contact_data.get("Email", ""),
                body=content
            )
            
            self.db.add(email)
            self.db.commit()
            self.db.refresh(email)
            
            return email
            
        except Exception as e:
            raise Exception(f"Failed to generate email: {str(e)}")
    
    def process_csv_data(
        self,
        csv_data: List[Dict[str, Any]],
        user: User,
        template: Optional[EmailTemplate] = None,
        stage: str = "outreach",
        avoid_duplicates: bool = False,
        dedupe_with_friends: bool = False,
        friends_ids: Optional[List[int]] = None
    ) -> List[GeneratedEmail]:
        generated_emails = []
        already_emailed = set()
        # Build set of already emailed addresses for this user (and optionally friends)
        if avoid_duplicates:
            conditions = [GeneratedEmail.user_id == user.id]
            if dedupe_with_friends and friends_ids:
                conditions.append(GeneratedEmail.user_id.in_(friends_ids))
            query = self.db.query(GeneratedEmail.recipient_email).filter(or_(*conditions))
            emails = {r[0].lower() for r in query}
            already_emailed.update(emails)

        for contact in csv_data:
            email_addr = contact.get("Email", "").lower()
            if not email_addr:
                continue
            if avoid_duplicates and email_addr in already_emailed:
                continue
            try:
                email = self.generate_personalized_email(contact, user, template, stage)
                generated_emails.append(email)
                if avoid_duplicates:
                    already_emailed.add(email_addr)
            except Exception as e:
                print(f"Error generating email for {email_addr}: {str(e)}")
        return generated_emails 

    def generate_followup_email(
        self,
        original_email: GeneratedEmail,
        user: User,
        template: Optional[EmailTemplate] = None
    ) -> GeneratedEmail:
        """Generate a follow-up email based on an original email"""
        
        # If no template provided, try to get the default template for followup category
        if not template:
            template = self.db.query(EmailTemplate).filter(
                EmailTemplate.user_id == user.id,
                EmailTemplate.category == "followup",
                EmailTemplate.is_default == True
            ).first()
        
        # Extract information from the original email
        recipient_name = original_email.recipient_name
        recipient_company = original_email.recipient_company
        recipient_email = original_email.recipient_email
        
        # If we have a template, use it instead of AI generation
        if template:
            # Use the template content and personalize it
            content = template.content
            
            # Replace placeholders with actual data
            content = content.replace("[Recipient Name]", recipient_name)
            content = content.replace("[Company Name]", recipient_company)
            content = content.replace("[Your Name]", user.full_name if user.full_name else "[Your Name]")
            content = content.replace("[Your Position]", user.position if user.position else "[Your Position]")
            content = content.replace("[Your Company]", user.company_name if user.company_name else "[Your Company]")
            
            # Extract subject from first line if it contains "Subject:"
            content_lines = content.split('\n')
            subject = "Follow-up: " + original_email.subject
            if content_lines[0].strip().lower().startswith("subject:"):
                subject = content_lines[0].strip()[8:].strip()
                content = '\n'.join(content_lines[1:]).strip()
            
            # Add signature if not present
            if not any(signature_indicator in content.lower() for signature_indicator in ["best regards", "sincerely", "kind regards"]):
                signature = f"""
Best regards,
{user.full_name if user.full_name else "[Your Name]"}
{user.position if user.position else "[Your Position]"}
{user.company_name if user.company_name else "[Your Company]"}"""
                content = f"{content}\n\n{signature}"
        else:
            # Use AI generation as fallback
            # Build context for OpenAI API
            prompt = f"""
            Create a follow-up email in English for a prospect who didn't respond to the initial outreach.
            
            Recipient Information:
            Name: {recipient_name}
            Company: {recipient_company}
            Email: {recipient_email}
            
            Original Email Subject: {original_email.subject}
            Original Email Content: {original_email.content}
            
            Sender Information:
            Name: {user.full_name if user.full_name else "[Your Name]"}
            Position: {user.position if user.position else "[Your Position]"}
            Company: {user.company_name if user.company_name else "[Your Company]"}
            Company Description: {user.company_description if user.company_description else "[brief description of company]"}
            
            Please generate a professional follow-up email that:
            1. References the previous email sent to them
            2. Is polite and not pushy
            3. Offers additional value or information
            4. Has a different angle or approach than the original
            5. Includes a clear but gentle call to action
            6. Is concise (2-3 short paragraphs maximum)
            7. Maintains a professional yet friendly tone
            8. Avoids being repetitive or aggressive
            9. If a company description is provided, use it to reinforce the value proposition
            
            The follow-up should feel natural and add value, not just be a reminder.
            """
            
            try:
                response = self.client.chat.completions.create(
                    model=AZURE_DEPLOYMENT_NAME,
                    messages=[
                        {"role": "system", "content": "You are an expert email writer specializing in professional follow-up emails. Create emails that add value and feel natural, not pushy. Do not use any markdown formatting (like ** or *) in the email content."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=800
                )
                
                generated_content = response.choices[0].message.content
                
                # Extract subject from first line of content and remove "Subject: " prefix if present
                content_lines = generated_content.split('\n')
                subject = content_lines[0].strip()
                if subject.lower().startswith("subject: "):
                    subject = subject[9:].strip()
                
                # Find the "Best regards" line and remove everything after it
                content = []
                for line in content_lines[1:]:
                    if line.strip().lower() == "best regards,":
                        break
                    content.append(line)
                
                # Join the content and add the correct signature
                content = '\n'.join(content).strip()
                
                # Remove any markdown formatting
                content = content.replace("**", "")
                
                # Replace placeholders with user information if available
                content = content.replace("[Your Name]", user.full_name if user.full_name else "[Your Name]")
                content = content.replace("[Your Position]", user.position if user.position else "[Your Position]")
                content = content.replace("[Your Company]", user.company_name if user.company_name else "[Your Company]")
                
                # Remove any existing signature lines after "Best regards" or similar phrases
                content_lines = content.split('\n')
                new_content = []
                signature_indicators = ["best regards", "sincerely", "kind regards", "warm regards", "looking forward", "thank you"]
                
                for line in content_lines:
                    line_lower = line.strip().lower()
                    if any(indicator in line_lower for indicator in signature_indicators):
                        break
                    new_content.append(line)
                
                content = '\n'.join(new_content).strip()
                
                # Add consistent signature format
                signature = f"""
Best regards,
{user.full_name if user.full_name else "[Your Name]"}
{user.position if user.position else "[Your Position]"}
{user.company_name if user.company_name else "[Your Company]"}"""
                
                content = f"{content}\n\n{signature}"
                
            except Exception as e:
                raise Exception(f"Failed to generate follow-up email: {str(e)}")
        
        # Create and save the follow-up email
        now = datetime.utcnow()
        followup_email = GeneratedEmail(
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            recipient_company=recipient_company,
            subject=subject,
            content=content,
            user_id=user.id,
            template_id=template.id if template else None,
            status="draft",  # Start as draft so user can review
            stage="followup",
            follow_up_status="none",
            follow_up_date=None,  # Will be set when sent
            final_follow_up_date=None,
            created_at=now,
            # Set legacy fields for backward compatibility
            to=recipient_email,
            body=content
        )
        
        self.db.add(followup_email)
        self.db.commit()
        self.db.refresh(followup_email)
        
        return followup_email 

    def generate_lastchance_email(
        self,
        original_email: GeneratedEmail,
        user: User,
        template: Optional[EmailTemplate] = None
    ) -> GeneratedEmail:
        """Generate a last chance email based on an original email"""
        
        # If no template provided, try to get the default template for lastchance category
        if not template:
            template = self.db.query(EmailTemplate).filter(
                EmailTemplate.user_id == user.id,
                EmailTemplate.category == "lastchance",
                EmailTemplate.is_default == True
            ).first()
        
        # Extract information from the original email
        recipient_name = original_email.recipient_name
        recipient_company = original_email.recipient_company
        recipient_email = original_email.recipient_email
        
        # If we have a template, use it instead of AI generation
        if template:
            # Use the template content and personalize it
            content = template.content
            
            # Replace placeholders with actual data
            content = content.replace("[Recipient Name]", recipient_name)
            content = content.replace("[Company Name]", recipient_company)
            content = content.replace("[Your Name]", user.full_name if user.full_name else "[Your Name]")
            content = content.replace("[Your Position]", user.position if user.position else "[Your Position]")
            content = content.replace("[Your Company]", user.company_name if user.company_name else "[Your Company]")
            
            # Extract subject from first line if it contains "Subject:"
            content_lines = content.split('\n')
            subject = "Final Follow-up: " + original_email.subject
            if content_lines[0].strip().lower().startswith("subject:"):
                subject = content_lines[0].strip()[8:].strip()
                content = '\n'.join(content_lines[1:]).strip()
            
            # Add signature if not present
            if not any(signature_indicator in content.lower() for signature_indicator in ["best regards", "sincerely", "kind regards"]):
                signature = f"""
Best regards,
{user.full_name if user.full_name else "[Your Name]"}
{user.position if user.position else "[Your Position]"}
{user.company_name if user.company_name else "[Your Company]"}"""
                content = f"{content}\n\n{signature}"
        else:
            # Use AI generation as fallback
            # Build context for OpenAI API
            prompt = f"""
            Create a final follow-up (last chance) email in English for a prospect who didn't respond to previous outreach attempts.
            
            Recipient Information:
            Name: {recipient_name}
            Company: {recipient_company}
            Email: {recipient_email}
            
            Original Email Subject: {original_email.subject}
            Original Email Content: {original_email.content}
            
            Sender Information:
            Name: {user.full_name if user.full_name else "[Your Name]"}
            Position: {user.position if user.position else "[Your Position]"}
            Company: {user.company_name if user.company_name else "[Your Company]"}
            Company Description: {user.company_description if user.company_description else "[brief description of company]"}
            
            Please generate a professional final follow-up email that:
            1. Acknowledges this is the final attempt to connect
            2. Is polite and professional, not desperate or pushy
            3. Offers a clear, compelling reason to respond now
            4. Provides a specific deadline or time-sensitive offer
            5. Includes a clear call to action
            6. Is concise (2-3 short paragraphs maximum)
            7. Maintains dignity and professionalism
            8. Leaves the door open for future contact
            9. If a company description is provided, use it to reinforce the value proposition
            
            This should feel like a final, respectful attempt to connect, not a desperate plea.
            """
            
            try:
                response = self.client.chat.completions.create(
                    model=AZURE_DEPLOYMENT_NAME,
                    messages=[
                        {"role": "system", "content": "You are an expert email writer specializing in professional final follow-up emails. Create emails that are respectful and professional, not desperate or pushy. Do not use any markdown formatting (like ** or *) in the email content."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=800
                )
                
                generated_content = response.choices[0].message.content
                
                # Extract subject from first line of content and remove "Subject: " prefix if present
                content_lines = generated_content.split('\n')
                subject = content_lines[0].strip()
                if subject.lower().startswith("subject: "):
                    subject = subject[9:].strip()
                
                # Find the "Best regards" line and remove everything after it
                content = []
                for line in content_lines[1:]:
                    if line.strip().lower() == "best regards,":
                        break
                    content.append(line)
                
                # Join the content and add the correct signature
                content = '\n'.join(content).strip()
                
                # Remove any markdown formatting
                content = content.replace("**", "")
                
                # Replace placeholders with user information if available
                content = content.replace("[Your Name]", user.full_name if user.full_name else "[Your Name]")
                content = content.replace("[Your Position]", user.position if user.position else "[Your Position]")
                content = content.replace("[Your Company]", user.company_name if user.company_name else "[Your Company]")
                
                # Remove any existing signature lines after "Best regards" or similar phrases
                content_lines = content.split('\n')
                new_content = []
                signature_indicators = ["best regards", "sincerely", "kind regards", "warm regards", "looking forward", "thank you"]
                
                for line in content_lines:
                    line_lower = line.strip().lower()
                    if any(indicator in line_lower for indicator in signature_indicators):
                        break
                    new_content.append(line)
                
                content = '\n'.join(new_content).strip()
                
                # Add consistent signature format
                signature = f"""
Best regards,
{user.full_name if user.full_name else "[Your Name]"}
{user.position if user.position else "[Your Position]"}
{user.company_name if user.company_name else "[Your Company]"}"""
                
                content = f"{content}\n\n{signature}"
                
            except Exception as e:
                raise Exception(f"Failed to generate last chance email: {str(e)}")
        
        # Create and save the last chance email
        now = datetime.utcnow()
        lastchance_email = GeneratedEmail(
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            recipient_company=recipient_company,
            subject=subject,
            content=content,
            user_id=user.id,
            template_id=template.id if template else None,
            status="draft",  # Start as draft so user can review
            stage="lastchance",
            follow_up_status="none",
            follow_up_date=None,  # Will be set when sent
            final_follow_up_date=None,
            created_at=now,
            # Set legacy fields for backward compatibility
            to=recipient_email,
            body=content
        )
        
        self.db.add(lastchance_email)
        self.db.commit()
        self.db.refresh(lastchance_email)
        
        return lastchance_email 
