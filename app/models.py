from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class TaskAssignedPayload(BaseModel):
    event: Literal["task_assigned"]
    task_id: str
    title: str
    assigned_to_name: str = ""
    assigned_to_email: str = ""
    assigned_to_account_id: str = ""


class TaskCompletedPayload(BaseModel):
    event: Literal["task_completed"]
    task_id: str
    title: str
    created_by_name: str = ""
    created_by_email: str = ""
    created_by_account_id: str = ""
    completed_by: str = ""


class InvolvedParties(BaseModel):
    creator_email: str = ""
    creator_account_id: str = ""
    assignee_email: str = ""
    assignee_account_id: str = ""


class NewCommentPayload(BaseModel):
    event: Literal["new_comment"]
    task_id: str
    title: str
    comment_author: str = ""
    comment_author_email: str = ""
    comment_author_account_id: str = ""
    comment_text: str = ""
    involved_parties: InvolvedParties = Field(default_factory=InvolvedParties)


JiraWebhookPayload = Annotated[
    Union[TaskAssignedPayload, TaskCompletedPayload, NewCommentPayload],
    Field(discriminator="event"),
]
