class QoSProfile:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class ReliabilityPolicy:
    BEST_EFFORT = 1


class HistoryPolicy:
    KEEP_LAST = 1
