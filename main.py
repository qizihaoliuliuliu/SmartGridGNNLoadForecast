# -*- coding: utf-8 -*-
"""
Created on Wed Mar 18 16:02:07 2020

currently does not work when we exceed 20 nodes 

@author: Austin Bell
"""


import os, sys 
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import  re
import gc
import importlib

# ML
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


# user functions
from dataUtils import loadEnergyData, energyDataset, getDatasets, normalizeAdjMat
from processData import processData
from modelUtils import saveCheckpoint, loadCheckpoint, plotPredVsTrue, dotDict

########################################################################################
# Parameters
########################################################################################
torch.manual_seed(0)
np.random.seed(0)

# last three months
validation_range = ["2014-10-01 00:00:00", "2014-12-31 23:00:00"]
validation_range = [datetime.strptime(date, '%Y-%m-%d %H:%M:%S') for date in validation_range]

##### Load our args
# config_file = sys.argv[1]#"STGLSTM_metadata_config"
config_file = "STGLSTM_metadata_config"

c = importlib.import_module("configs."+config_file)
args = c.args

print(args)

##### import correct model
model_funcs = importlib.import_module("models."+args.model)
STGNN = model_funcs.STGNN

# data directories
processed_dir = "./data/processed/"

########################################################################################
# Data Prep
########################################################################################

# only load energy demand if we are not loading our data
if args.load_seq:
    # get number of nodes to include
    files = os.listdir(args.seq_path)
    incl_nodes = max([int(re.search("\d{1,5}", f).group(0)) for f in files if re.search("\d", f)])
    
    print("loading data")
    _, adj_mat = loadEnergyData(processed_dir, incl_nodes = incl_nodes, partial = False)
    energy_demand = None
else:
    energy_demand, adj_mat = loadEnergyData(processed_dir, incl_nodes = "All", partial = False)


# format for pytorch
train_dataset, val_dataset = getDatasets(args, energy_demand, validation_range)

# stop if we are just save sequences
if args.save_seq:
    sys.exit()

train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False)
print("loaded Data Loaders")


# normalized adjacency matrix with self loop
adj_norm = normalizeAdjMat(adj_mat)

########################################################################################
# Network Definition
########################################################################################
num_nodes = train_dataset.target.shape[1]
num_features = train_dataset.inputs.shape[3]

#del train_dataset, val_dataset, adj_mat
gc.collect()


# Model init
Gnet = STGNN(num_nodes,
             num_features,
             args.historical_input,
             args.forecast_output-1,
             args).to(device=args.device)

# SGD and Loss
optimizer = torch.optim.Adam(Gnet.parameters(), lr=args.lr)
scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=args.steps, gamma=0.5)

criterion = nn.MSELoss()


train_loss = []
val_loss = []
val_best = 1
########################################################################################
# Training the Network
########################################################################################

for epoch in range(args.epochs):
    print("Epoch Number: " + str(epoch + 1))
    
    
    # tracking     
    epoch_trn_loss = []
    epoch_val_loss = []
    
    
    adj_norm = adj_norm.to(args.device) 
    
    
    ###########################################################
    # Training the network
    ###########################################################
    Gnet.train()
    for batch_idx, (features, metadata, target) in enumerate(train_loader):
        features = features.to(args.device)
        metadata = metadata.to(args.device)
        target = target.to(args.device)
        
        optimizer.zero_grad()
        
        
        predicted = Gnet(features, metadata, adj_norm)
        predicted.shape
        loss = criterion(predicted, target)
        
        loss.backward()
        optimizer.step()
        
        # update tracking
        np_loss = loss.detach().cpu().numpy()
        epoch_trn_loss.append(np_loss)
        
        
    
    ###########################################################
    # Network validation
    ###########################################################
    # making some poor memory choices, but easier to debug for now
    val_predictions = []
    val_target = []
    with torch.no_grad():
        Gnet.eval()
        for vbatch_idx, (vfeatures, vmetadata, vtarget) in enumerate(val_loader):
            vfeatures = vfeatures.to(args.device)
            vmetadata = vmetadata.to(args.device)
            vtarget = vtarget.to(args.device)
            
            vpreds = Gnet(vfeatures, vmetadata, adj_norm)
            vloss = criterion(vpreds, vtarget)
            
            # storage and tracking
            np_vloss = vloss.detach().cpu().numpy()
            np_vpreds = vpreds.detach().cpu().numpy()
            np_vtarget = vtarget.detach().cpu().numpy()
            epoch_val_loss.append(np_vloss)
            val_predictions.append(np_vpreds)
            val_target.append(np_vtarget)
            
            
            
    scheduler.step()
    
    # store epoch losses 
    train_loss.append(np.mean(epoch_trn_loss))
    val_loss.append(np.mean(epoch_val_loss))
    val_predictions = np.concatenate(val_predictions)
    val_target = np.concatenate(val_target)
    
    # If validation imporves then save model 
    if val_loss[-1] < val_best:
        val_best = val_loss[-1]
        saveCheckpoint(Gnet, filename = args.model_name)

    # show results
    #print(val_target[0][0], val_predictions[0][0])
    #print(val_target[0][1], val_predictions[0][1])
    print("Current Training Loss: " + str(round(train_loss[-1], 8)))
    print("Current Validation Loss: " + str(round(val_loss[-1], 8)))
    print("\n")
    

    
plt.title('Train & Validation MSE Loss')
plt.plot(train_loss, label = "Training Loss")
plt.plot(val_loss, label = "Validation Loss")
plt.legend()
plt.show()
plt.ylim(0,.1)
 
plotPredVsTrue(val_target, val_predictions, 2, 2)

