from typing import Optional, Union, Tuple
from tinygrad.tensor import Tensor

class BatchNorm2d:
  def __init__(self, sz, eps=1e-5, affine=True, track_running_stats=True, momentum=0.1):
    assert affine, "BatchNorm2d is only supported with affine"
    self.eps, self.track_running_stats, self.momentum = eps, track_running_stats, momentum

    self.weight, self.bias = Tensor.ones(sz), Tensor.zeros(sz)

    self.running_mean, self.running_var = Tensor.zeros(sz, requires_grad=False), Tensor.ones(sz, requires_grad=False)
    self.num_batches_tracked = Tensor.zeros(1, requires_grad=False)

  def __call__(self, x:Tensor):
    if Tensor.training:
      # This requires two full memory accesses to x
      # https://github.com/pytorch/pytorch/blob/c618dc13d2aa23625cb0d7ada694137532a4fa33/aten/src/ATen/native/cuda/Normalization.cuh
      # There's "online" algorithms that fix this, like https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance#Welford's_Online_algorithm
      x_detached = x.detach()
      batch_mean = x_detached.mean(axis=(0,2,3))
      y = (x_detached - batch_mean.reshape(shape=[1, -1, 1, 1]))
      batch_var = (y*y).mean(axis=(0,2,3))
      batch_invstd = batch_var.add(self.eps).pow(-0.5)
      self.batch_invstd = None

      # NOTE: wow, this is done all throughout training in most PyTorch models
      if self.track_running_stats:
        self.running_mean.assign((1 - self.momentum) * self.running_mean + self.momentum * batch_mean)
        self.running_var.assign((1 - self.momentum) * self.running_var + self.momentum * batch_var)
        self.num_batches_tracked += 1
    else:
      batch_mean, batch_var = self.running_mean, self.running_var
      # NOTE: this can be precomputed for static inference. if you manually update running_var, you have to reset this
      if not hasattr(self, "batch_invstd") or not self.batch_invstd:
        self.batch_invstd = batch_var.add(self.eps).pow(-0.5)
      batch_invstd = self.batch_invstd

    return x.batchnorm(self.weight, self.bias, batch_mean, batch_invstd)

# TODO: is this good weight init?
class Conv2d:
  def __init__(self, in_channels, out_channels, kernel_size, stride=1, padding=0, dilation=1, groups=1, bias=True):
    self.kernel_size = (kernel_size, kernel_size) if isinstance(kernel_size, int) else (kernel_size[0], kernel_size[1])
    self.stride, self.padding, self.dilation, self.groups = stride, padding, dilation, groups
    self.weight = Tensor.glorot_uniform(out_channels, in_channels//groups, self.kernel_size[0], self.kernel_size[1])
    self.bias = Tensor.zeros(out_channels) if bias else None

  def __call__(self, x):
    return x.conv2d(self.weight, self.bias, padding=self.padding, stride=self.stride, dilation=self.dilation, groups=self.groups)

class Linear:
  def __init__(self, in_features, out_features, bias=True):
    self.weight = Tensor.glorot_uniform(out_features, in_features)
    self.bias = Tensor.zeros(out_features) if bias else None

  def __call__(self, x):
    return x.linear(self.weight.transpose(), self.bias)

class GroupNorm:
  def __init__(self, num_groups:int, num_channels:int, eps:float=1e-5, affine:bool=True):
    self.num_groups, self.num_channels, self.eps = num_groups, num_channels, eps
    self.weight : Optional[Tensor] = Tensor.ones(num_channels) if affine else None
    self.bias : Optional[Tensor] = Tensor.zeros(num_channels) if affine else None

  def __call__(self, x:Tensor):
    # reshape for layernorm to work as group norm
    # subtract mean and divide stddev
    x = x.reshape(x.shape[0], self.num_groups, -1).layernorm(eps=self.eps).reshape(x.shape)

    if self.weight is None or self.bias is None: return x
    # elementwise_affine on channels
    return x * self.weight.reshape(1, -1, 1, 1) + self.bias.reshape(1, -1, 1, 1)

class LayerNorm:
  def __init__(self, normalized_shape:Union[int, Tuple[int, ...]], eps:float=1e-5, elementwise_affine:bool=True):
    normalized_shape = (normalized_shape,) if isinstance(normalized_shape, int) else tuple(normalized_shape)
    self.axis, self.eps, self.elementwise_affine = tuple(-1-i for i in range(len(normalized_shape))), eps, elementwise_affine
    self.weight, self.bias = (Tensor.ones(*normalized_shape), Tensor.zeros(*normalized_shape)) if elementwise_affine else (None, None)

  def __call__(self, x:Tensor):
    x = x.layernorm(eps=self.eps, axis=self.axis)
    if not self.elementwise_affine: return x
    return x * self.weight + self.bias
