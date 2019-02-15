# -*- coding: utf-8 -*-
"""Modeling Censored Time to Event Data with Pyro

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1AWwBZ5S1hLEht2oSe1BiyDGHPLtqwt-N
"""

# we install the CPU-only version of torch here, since the download is fast
!pip install https://download.pytorch.org/whl/cpu/torch-1.0.0-cp36-cp36m-linux_x86_64.whl
!pip install pyro-ppl

import pyro 
import torch 
import pyro.distributions as dist 

import numpy as np 

import seaborn as sns 

from pyro import infer, optim

from pyro.infer.mcmc import HMC, MCMC
from pyro.infer import EmpiricalMarginal

assert pyro.__version__.startswith('0.3')

"""Let's first generate random samples:"""

n = 500
a = 2
b = 4
c = 8

x = dist.Normal(0, 0.34).sample((n,))

link = torch.nn.functional.softplus(torch.tensor(a*x + b))
y = dist.Exponential(rate=1 / link).sample()  # note param is rate, not mean

truncation_label = (y > c).float()

y_obs = y.clamp(max=c)

sns.regplot(x.numpy(), y.numpy())
sns.regplot(x.numpy(), y_obs.numpy())

"""# Modeling using HMC 

Here we will start with a basic model that uses HMC to conduct inference. Here the model is specified in such a way that each individual sample will be looped through sequentially. As a result this can be very slow. So we just let it run a few iterations for demonstration purpose. 

In the next section, we'll introduct much faster way of specifying the model.
"""

def model(x, y, truncation_label):
  a_model = pyro.sample("a_model", dist.Normal(0, 10))
  b_model = pyro.sample("b_model", dist.Normal(0, 10))
  
  link = torch.nn.functional.softplus(a_model * x + b_model)
  
  for i in range(len(x)):
    y_hidden_dist = dist.Exponential(1 / link[i])
    
    if truncation_label[i] == 0: 
      y_real = pyro.sample("obs_{}".format(i), 
                           y_hidden_dist,
                           obs = y[i])
    else:
      truncation_prob = 1 - y_hidden_dist.cdf(y[i])
      pyro.sample("truncation_label_{}".format(i), 
                  dist.Bernoulli(truncation_prob), 
                  obs = truncation_label[i])
      

pyro.clear_param_store()
hmc_kernel = HMC(model,
                 step_size = 0.1, 
                 num_steps = 4)

mcmc_run = MCMC(hmc_kernel, 
                num_samples=5,
                warmup_steps=1).run(x, y, truncation_label)

marginal_a = EmpiricalMarginal(mcmc_run, 
                               sites="a_model")

posterior_a = [marginal_a.sample() for i in range(50)] 

sns.distplot(posterior_a)

"""# Modeling using HMC with Vectorized Data

Here we try to make the estimation faster using the `plate` and `mask` function.
"""

def model(x, y, truncation_label):
  a_model = pyro.sample("a_model", dist.Normal(0, 10)) 
  b_model = pyro.sample("b_model", dist.Normal(0, 10))
  
  link = torch.nn.functional.softplus(a_model * x + b_model) 
  
  with pyro.plate("data"):
    y_hidden_dist = dist.Exponential(1 / link) 
    
    with pyro.poutine.mask(mask = (truncation_label == 0)): 
      pyro.sample("obs", y_hidden_dist,
                  obs = y)
      
    with pyro.poutine.mask(mask = (truncation_label == 1)):
      truncation_prob = 1 - y_hidden_dist.cdf(y)
      pyro.sample("truncation_label", 
                  dist.Bernoulli(truncation_prob), 
                  obs = torch.tensor(1.))
      
      
      
pyro.clear_param_store()
hmc_kernel = HMC(model,
                 step_size = 0.1, 
                 num_steps = 4)

mcmc_run = MCMC(hmc_kernel, 
                num_samples=500,
                warmup_steps=1000).run(x, y, truncation_label)

marginal_a = EmpiricalMarginal(mcmc_run, 
                               sites="a_model")

posterior_a = [marginal_a.sample() for i in range(100)] 

sns.distplot(posterior_a)

"""# Modeling with SVI

Here we make inference using Stochastic Variational Inference. However here we have to define a guide function.
"""

from pyro.contrib.autoguide import AutoMultivariateNormal

guide = AutoMultivariateNormal(model)

pyro.clear_param_store()
  
adam_params = {"lr": 0.01, "betas": (0.90, 0.999)}
optimizer = optim.Adam(adam_params)

svi = infer.SVI(model, 
                guide, 
                optimizer, 
                loss=infer.Trace_ELBO())

losses = []
for i in range(5000):
  loss = svi.step(x, y_obs, truncation_label)
  losses.append(loss)

  if i % 1000 == 0:
    print(', '.join(['{} = {}'.format(*kv) for kv in guide.median().items()]))

print('final result:')
for kv in sorted(guide.median().items()):
  print('median {} = {}'.format(*kv))

"""Let's check that the model has converged by plotting losses"""

sns.plt.plot(losses);

"""We can plot approximate posterior distribution using the [guide.quantiles()](http://docs.pyro.ai/en/dev/contrib.autoguide.html#pyro.contrib.autoguide.AutoContinuous.quantiles) function:"""

N = 1000
for name, quantiles in guide.quantiles(torch.arange(0., N) / N).items():
  quantiles = np.array(quantiles)
  pdf = 1 / (quantiles[1:] - quantiles[:-1]) / N
  x = (quantiles[1:] + quantiles[:-1]) / 2
  sns.plt.plot(x, pdf, label=name)
  
sns.plt.legend()
sns.plt.ylabel('density')

