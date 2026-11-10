from enum import Enum


class RequirementStatus(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'
    INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE'


class ReleaseStatus(str, Enum):
    READY = 'READY'
    BLOCKED = 'BLOCKED'
    NEEDS_REVIEW = 'NEEDS_REVIEW'


def overall_release_status(statuses):
    values = [RequirementStatus(s) for s in statuses]
    if RequirementStatus.FAIL in values:
        return ReleaseStatus.BLOCKED
    if not values or RequirementStatus.INSUFFICIENT_EVIDENCE in values:
        return ReleaseStatus.NEEDS_REVIEW
    return ReleaseStatus.READY
