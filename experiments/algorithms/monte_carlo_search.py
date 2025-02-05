import os
import sys
import ray

from ray import tune
from ray.tune.logger import pretty_print

parent_directory = os.path.join(os.environ["BLACK_BOX"])
sys.path.append(parent_directory)

from experiments.utils import validation_utils
from experiments.agents.main_agent import MainAgent


if __name__ == "__main__":

    # get arguments
    args = validation_utils.argument_parser()
    args.algo_config_file = "monte_carlo_search.yaml"

    # config for specified algorithm
    algorithm_config = validation_utils.get_algorithm_config(args=args)
    print("\n[CONFIG]-> Algorithm Configuration:\t", pretty_print(algorithm_config))

    # initialize main agent class
    agent = MainAgent(
        algorithm_config    =       algorithm_config
    )
    print("\n[INFO]-> Agent Class:\t", agent)

    # construct search space
    distance_space, velocity_space = agent.create_search_space(
        params              =       algorithm_config['search_space']
    )
    print("\n[INFO]-> Distance Space:\t", distance_space)
    print("\n[INFO]-> Velocity Space:\t", velocity_space)

    # uniform search space configurations from given parameters
    search_configs = {
        'ego_v1'    : tune.uniform(velocity_space[0], velocity_space[-1]),
        'front_v1'  : tune.uniform(velocity_space[0], velocity_space[-1]),
        'front_v2'  : tune.uniform(velocity_space[0], velocity_space[-1]),
        'delta_dist': tune.uniform(distance_space[0], distance_space[-1])
    }
    print("\n[INFO]-> Search Space:\t", pretty_print(search_configs))
    
    # tuning configurations class -> new from ray v2.0.0
    tune_config = tune.TuneConfig(
        num_samples         =       algorithm_config["num_samples"]
    )
    print("\n[INFO]-> TuneConfig:\t", tune_config)

    # set project directory for all ray workers
    runtime_env = {
        "working_dir"       :       parent_directory,
        # exclude error and output files (relative path from "parent_directory")
        "excludes"          :       ["*.err", "*.out", "*.mp4", "*.gif", "*.png", "*.pdf", "*.pptx"]
    }
    ray.init(
        runtime_env         =       runtime_env
    )

    # execute validation search algorithm and save results to csv
    validation_utils.run_search_algorithm(
        agent               =       agent,
        validation_config   =       algorithm_config,
        tune_config         =       tune_config,
        param_space         =       search_configs
    )