from pydantic import BaseModel, Field


class IssueFields(BaseModel):
    """Shared Jira issue context sent by Automation webhooks."""

    site_name: str = ""
    module: str = Field(default="", description="Jira summary — your Module field")
    description: str = ""
    image_url: str = ""
    issue_url: str = ""

    def module_label(self, fallback_title: str = "") -> str:
        return self.module.strip() or fallback_title.strip() or "Untitled"
