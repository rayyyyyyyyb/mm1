import torch
from torch import nn

from src.utils.optimizer_receipts import OptimizerStepTracker, clip_gradients_with_receipt


def test_tracker_counts_actual_optimizer_steps() -> None:
    model = nn.Linear(2, 1)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    tracker = OptimizerStepTracker(optimizer)
    tracker.record_attempt()
    model(torch.ones(1, 2)).sum().backward()
    optimizer.step()
    assert tracker.attempted_steps == 1
    assert tracker.applied_steps == 1
    tracker.close()


def test_clip_receipt_reports_global_and_group_norms() -> None:
    first = nn.Parameter(torch.tensor([3.0, 4.0]))
    second = nn.Parameter(torch.tensor([0.0, 4.0]))
    first.grad = torch.tensor([3.0, 4.0])
    second.grad = torch.tensor([0.0, 4.0])
    groups = [
        {"group_name": "a", "params": [first]},
        {"group_name": "b", "params": [second]},
    ]
    pre, coefficient, norms, shares, clipped = clip_gradients_with_receipt([first, second], groups, 1.0)
    assert abs(pre - (41.0**0.5)) < 1e-6
    assert coefficient < 1.0
    assert set(norms) == {"a", "b"}
    assert abs(sum(shares.values()) - 1.0) < 1e-6
    assert clipped is True
