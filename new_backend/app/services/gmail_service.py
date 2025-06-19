import requests
import base64

def send_gmail_email(user, to_email, subject, body):
    """
    Sends an email using the user's Gmail account via the Gmail API.

    Args:
        user: User object with .gmail_access_token and .email attributes
        to_email: Recipient's email address
        subject: Email subject
        body: Email body text

    Returns:
        The Gmail API response JSON on success.

    Raises:
        Exception: If Gmail is not connected or sending fails.
    """
    access_token = user.gmail_access_token
    if not access_token:
        raise Exception("Gmail not connected")
    message = f"From: {user.email}\r\nTo: {to_email}\r\nSubject: {subject}\r\n\r\n{body}"
    raw = base64.urlsafe_b64encode(message.encode("utf-8")).decode("utf-8")
    url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {"raw": raw}
    resp = requests.post(url, headers=headers, json=data)
    if resp.status_code not in [200, 202]:
        raise Exception(f"Gmail sending failed: {resp.text}")
    return resp.json()

def check_reply(user, generated_email):
    """
    Checks if the prospect has replied to an email thread.

    Args:
        user: User object with .gmail_access_token and .email attributes
        generated_email: GeneratedEmail object with .thread_id and .recipient_email

    Returns:
        True if a reply is found from the recipient, False otherwise.
    """
    access_token = user.gmail_access_token
    if not access_token:
        raise Exception("Gmail not connected")
    thread_id = getattr(generated_email, "thread_id", None)
    recipient_email = getattr(generated_email, "recipient_email", None)
    if not thread_id or not recipient_email:
        return False

    url = f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}?format=full"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        # If the thread no longer exists or can't be read, treat as not replied
        return False

    data = resp.json()
    messages = data.get("messages", [])
    # Skip the first message (sent by user), check if any other message is from the recipient
    for msg in messages[1:]:
        headers_list = msg.get("payload", {}).get("headers", [])
        from_email = None
        for header in headers_list:
            if header.get("name", "").lower() == "from":
                from_email = header.get("value", "").lower()
                break
        if from_email and recipient_email.lower() in from_email:
            return True
    return False
