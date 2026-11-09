"""Contact suggestions extracted locally; never infer missing country codes."""
import re
from pydantic import EmailStr, TypeAdapter, ValidationError
from ..agents.interview.phone import contact_numbers


def contacts(text):
    emails=[]
    for candidate in re.findall(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',text):
        try:email=str(TypeAdapter(EmailStr).validate_python(candidate))
        except ValidationError:continue
        if email.casefold() not in {e.casefold() for e in emails}:emails.append(email)
    return {'suggested_emails':emails,'suggested_numbers':contact_numbers(text)}
