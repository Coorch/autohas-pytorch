'''
Strategy for training AutoHAS controller

from module.controller import Controller

# randomly initialize supermodel weights and sampling probabilities
controller = Controller()

# split data into training and validation sets
D_train, D_val = training_data.split()

while not controller.has_converged():
    # sample `controller` for a model and hyperparameters
    candidate_model, hyperparams = controller.sample()    

    # optimize `candidate_model`
    using hyperparams as hyperparameters:
        candidate_model.train(hyperparams)

    # then, we update the supermodel's shared weights (or at least the 
    # ones contained in `candidate_model`)
    controller.supermodel.update(candidate_model_copy.weights)

    # use copy of `candidate_model` to calculate `controller` gradients
    candidate_model_copy = candidate_model.copy()
    using hyperparams as hyperparameters:
        quality = candidate_model_copy.calculate_validation_accuracy()
    controller.update(reward_signal=quality)

final_model, final_hyperparams = controller.sample()
save(final_model, final_hyperparams)
'''
from module.controller.mnist_controller import MNISTController
from torch.utils.tensorboard import SummaryWriter
import numpy as np
import torch
import copy

random_seed = 42                # torch seed
warmup_iterations = 0           # number of iterations before training controller
num_rollouts_per_iteration = 5  # number of child models evaluated before each controller update
exponential_reward = None       # compute model quality as `exponential_reward` ^ (validation accuracy)


torch.seed(random_seed)
device = torch.device('cuda:0') if torch.cuda.is_available() else torch.device('cpu')
controller = MNISTController(N=5, device=device, epochs=5, exponential_reward=exponential_reward)
logger = SummaryWriter()

logger.add_scalar('Random seed', random_seed)
logger.add_scalar('Warmup iterations', warmup_iterations)
logger.add_scalar('N rollout per iteration', num_rollouts_per_iteration)
logger.add_scalar('N training epochs', controller.archspace.epochs)
if exponential_reward:
    logger.add_scalar('Exponential reward', exponential_reward)


iteration = 0
print("Training controller...")
while not controller.has_converged():
    print("Iteration %d\n\n" % iteration, end='\r')

    rollouts = []
    for t in range(num_rollouts_per_iteration):
        print("\n\tTimestep %d" % t)
        # sample `controller` for a model and hyperparameters
        print("\tLoading child...")
        model_params, hp_params = controller.sample()
        hp_state = controller.hpspace[tuple([int(h) for h in hp_params])]
        hp_state = {'optimizer': hp_state[0], 'learning_rate': hp_state[1]}
        model_state, model_dict = controller.archspace[[int(i) for i in model_params]]
        print("\tChild is...")
        print(controller.archspace.child_repr(model_dict, indentation_level=2))

        # then, we update the supermodel's shared weights (or at least
        # the ones contained in `model_state`)
        print("\tTraining child...")
        controller.archspace.train_child(model_state, hp_state, indentation_level=2)
        for layer_name in model_dict:
            # save weights layer-wise
            layer = model_state[model_dict[layer_name]]
            controller.archspace._save_layer_weights(layer, layer_name)

        # then, evaluate child quality
        print("\tEvaluating child quality...", end='\r')
        model_state_copy = copy.deepcopy(model_state)
        model_params_copy, hp_params_copy = copy.deepcopy(model_params), copy.deepcopy(hp_params)
        quality = controller.archspace.get_reward_signal(model_state_copy)
        rollouts.append([model_params_copy, hp_params_copy, quality])
        print("\tChild quality is %f" % quality)

    # then, we update `controller` using copied model(i.e. sampling probabilities)
    # and determine if we've reached convergence
    if warmup_iterations >= 0 and iteration >= warmup_iterations:
        print("\tUpdating controller...")
        controller.update(rollouts)

        # Determine validation accuracy of most likely child candidate
        print("\n\n\tLoading argmax child...")
        model_params, hp_params = controller.policy_argmax()
        hp_state = controller.hpspace[tuple([int(h) for h in hp_params])]
        hp_state = {'optimizer': hp_state[0], 'learning_rate': hp_state[1]}
        model_state, model_dict = controller.archspace[[int(i) for i in model_params]]
        print("\tArgmax child is...")
        print(controller.archspace.child_repr(model_dict, indentation_level=2))

        print("\tTraining argmax child...")
        controller.archspace.train_child(model_state, hp_state, indentation_level=2)

        print("\tEvaluating argmax child quality...", end='\r')
        quality = controller.archspace.get_reward_signal(model_state)
        print("\tArgmax child quality is %f" % quality)

        logger.add_scalar('Accuracy/argmax', quality, iteration)

        if quality > 0.95:
            controller.converged = True

    else:
        print("\tNot updating controller!")

    average_quality = np.mean([r[2] for r in rollouts])
    logger.add_scalar('Accuracy/val', average_quality, iteration)
    print("\tAverage child quality over rollout is %f" % average_quality)

    # save histograms of controller policy weights
    print("\tController policies...")
    for p in controller.policies['archspace']:
        params = controller.policies['archspace'][p].state_dict()['params']
        params /= torch.sum(params)
        logger.add_scalars(
            'Parameters/Policy %d Normalized Parameters' % p,
            {'param %d' % i: params[i] for i in range(len(params))},
            iteration
        )
        logger.add_histogram('Policy %d Normalized Parameters' % p, params, iteration)

    # periodically save controller policy weights
    if iteration % 5 == 0:
        controller.save_policies()

    iteration += 1
    
# save final controller policy weights after convergence
controller.save_policies('mnistcontroller_weights_converged')