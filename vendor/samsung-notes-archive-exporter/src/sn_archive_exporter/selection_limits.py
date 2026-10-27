from __future__ import annotations


# Samsung Notes has been observed to disable some selection actions at 100+
# selected files. Keep automated export batches below that UI threshold.
MAX_EXPORT_SELECTION_COUNT = 99
