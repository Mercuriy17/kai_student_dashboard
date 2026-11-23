from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    grade_recorded = Signal(int)      # subject_id
    task_updated = Signal(int)        # task_id
    schedule_changed = Signal()
    sync_staged = Signal(int)         # count of pending AgentChange items