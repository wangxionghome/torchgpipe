import weakref

import pytest
import torch

from torchgpipe.dependency import Fork, Join, fork, join


@pytest.mark.skipif(not torch.cuda.is_available(), reason='cuda required')
def test_fork_join():
    logs = []

    class Log(torch.autograd.Function):
        @staticmethod
        def forward(ctx, number, tensor):
            ctx.number = number
            return tensor.detach()

        @staticmethod
        def backward(ctx, grad):
            logs.append(ctx.number)
            return None, grad

    a = torch.rand(1, device='cpu', requires_grad=True)
    b = torch.rand(1, device='cuda', requires_grad=True)

    a = Log.apply(1, a)

    a, phony = fork(a)
    b = join(a, phony)

    b = Log.apply(2, b)
    b = b.to('cpu')

    (a+b).backward()

    assert logs == [2, 1]


def test_fork_join_enable_grad():
    x = torch.rand(1, requires_grad=True)

    with torch.enable_grad():
        x2, p = fork(x)

    assert p.requires_grad
    assert x2 is not x
    x = x2

    assert x.requires_grad
    assert p.requires_grad
    assert x.grad_fn.__class__ is Fork._backward_cls
    assert p.grad_fn.__class__ is Fork._backward_cls

    with torch.enable_grad():
        x2 = join(x, p)

    assert x2 is not x
    x = x2

    assert x.requires_grad
    assert x.grad_fn.__class__ is Join._backward_cls


def test_fork_join_no_grad(monkeypatch):
    def do_not_apply(*args):
        raise AssertionError('Function.apply called')
    monkeypatch.setattr('torch.autograd.Function.apply', do_not_apply)

    x = torch.rand(1, requires_grad=True)

    with torch.no_grad():
        x2, p = fork(x)

    assert not p.requires_grad
    assert x2 is x
    x = x2

    with torch.no_grad():
        x2 = join(x, p)

    assert x2 is x
    x = x2


def test_fork_leak():
    leak = None

    class F(torch.autograd.Function):
        @staticmethod
        def forward(ctx, input):
            return input

        @staticmethod
        def backward(ctx, grad):
            nonlocal leak
            leak = weakref.ref(ctx)
            return grad

    x = torch.rand(1, requires_grad=True)
    x = F.apply(x)
    x, phony = fork(x)
    x = join(x, phony)

    x.backward()
    del x, phony

    assert leak() is None
