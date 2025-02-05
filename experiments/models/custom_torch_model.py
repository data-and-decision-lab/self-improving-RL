import gym
import numpy as np

from typing import Optional
from ray.rllib.utils import try_import_torch
from ray.rllib.utils.annotations import override
from ray.rllib.utils.typing import List, Dict, TensorType, ModelConfigDict
from ray.rllib.models.utils import get_activation_fn
from ray.rllib.models.torch.torch_modelv2 import TorchModelV2
from ray.rllib.models.torch.misc import SlimFC, AppendBiasLayer, normc_initializer
from ray.rllib.models.preprocessors import get_preprocessor

torch, nn = try_import_torch()


class CustomTorchModel(TorchModelV2, nn.Module):

    def __init__(self,
                obs_space: gym.spaces.Space,
                action_space: gym.spaces.Space,
                num_outputs: int,
                model_config: ModelConfigDict,
                name: str,
                **customized_model_kwargs):
        TorchModelV2.__init__(self, obs_space, action_space, num_outputs, model_config, name)
        nn.Module.__init__(self)

        self.free_log_std = model_config.get("free_log_std")
        if self.free_log_std:
            assert num_outputs % 2 == 0, ("num_outputs must be divisible by two", num_outputs)
            num_outputs = num_outputs // 2
        
        input_size = get_preprocessor(obs_space)(obs_space).size
        output_size = get_preprocessor(action_space)(action_space).size

        # add hidden layers for policy network
        policy_layers = []
        prev_layer_size = int(np.product(obs_space.shape))

        for size in model_config["custom_model_config"]["policy_fcnet_hiddens"]:
            policy_layers.append(
                SlimFC(
                    in_size         =   prev_layer_size,
                    out_size        =   size,
                    initializer     =   normc_initializer(1.0),
                    activation_fn   =   get_activation_fn(
                        model_config["custom_model_config"]["policy_hidden_activation"],
                        framework   =   "torch"
                    )
                )
            )
            prev_layer_size = size

            # add a batch norm layer
            # policy_layers.append(nn.BatchNorm1d(prev_layer_size))
        
        # put everything in sequence to build a parallel set of hidden layers for the policy network
        self.policy_hiddens = nn.Sequential(*policy_layers)
        
        # add main policy action layer
        self.policy_branch = SlimFC(
            in_size         =   prev_layer_size,
            out_size        =   output_size,
            initializer     =   normc_initializer(0.01),
            activation_fn   =   get_activation_fn(
                model_config["custom_model_config"]["action_layer_activation"],
                framework   =   "torch"
            )
        )

        # layer to add the log std vars to the state-dependent means
        if self.free_log_std:
            self.append_free_log_std = AppendBiasLayer(num_outputs)

        # add hidden layers for value network
        value_layers = []
        prev_layer_size = int(np.product(obs_space.shape))

        for size in model_config["custom_model_config"]["value_fcnet_hiddens"]:
            value_layers.append(
                SlimFC(
                    in_size         =   prev_layer_size,
                    out_size        =   size,
                    initializer     =   normc_initializer(1.0),
                    activation_fn   =   get_activation_fn(
                        model_config["custom_model_config"]["value_hidden_activation"],
                        framework   =   "torch"
                    )
                )
            )
            prev_layer_size = size

            # add a batch norm layer
            # value_layers.append(nn.BatchNorm1d(prev_layer_size))
        
        # build a parallel set of hidden layers for the value network
        self.value_hiddens = nn.Sequential(*value_layers)

        # add value function layer
        self.value_branch = SlimFC(
            in_size         =   prev_layer_size,
            out_size        =   1,
            initializer     =   normc_initializer(1.0),
            activation_fn   =   get_activation_fn(
                model_config["custom_model_config"]["value_layer_activation"],
                framework   =   "torch"
            )
        )
    
    @override(TorchModelV2)
    def forward(self, input_dict: Dict[str, TensorType], state: Optional[List[TensorType]] = [], seq_lens: Optional[TensorType] = None) -> tuple:
        obs = input_dict["obs"].float()
        obs = obs.reshape(obs.shape[0], -1)

        self.policy_hidden_out = self.policy_hiddens(obs)
        self.value_hidden_out = self.value_hiddens(obs)

        # pass through main policy action layer
        policy_out = self.policy_branch(self.policy_hidden_out)

        # acceleration is from 0 ti 1;  braking is from 0 to -1
        accel_brake = policy_out[:, 0].reshape(-1, 1)
        
        # only %50 of the steering command will be used
        steer = 0.5 * policy_out[:, 1].reshape(-1, 1)

        # apply tangent hyperbolic activation functions to actions
        accel_brake = torch.tanh(accel_brake)
        steer = torch.tanh(steer)
        
        policy_out = torch.cat((steer, accel_brake), 1)

        if self.free_log_std:
            policy_out = self.append_free_log_std(policy_out)
        
        return policy_out, state

    @override(TorchModelV2)
    def value_function(self) -> torch.tensor:
        assert self.value_hidden_out is not None, "must call forward first!"
        value_out = self.value_branch(self.value_hidden_out)

        return value_out.squeeze(1)
