// Configuration for the a machine comprehension model based on:
//   Seo, Min Joon et al. “Bidirectional Attention Flow for Machine Comprehension.”
//   ArXiv/1611.01603 (2016)
{
  "dataset_reader": {
    "type": "squad",
    "token_indexers": {
      "tokens": {
        "type": "single_id",
        "lowercase_tokens": true
      }
    }
  },
  "train_data_path": "extrinsic_tasks/datasets/squad/squad-train-v1.1.json",
  "validation_data_path": "extrinsic_tasks/datasets/squad/squad-dev-v1.1.json",
  "model": {
    "type": "bidaf",
    "text_field_embedder": {
        "token_embedders": {
            "tokens": {
                "type": "embedding",
                "pretrained_file": "${emb_filetxt}",
                "embedding_dim": ${task_emb_size},
                "trainable": false
            },
        }
    },
    "num_highway_layers": 2,
    "phrase_layer": {
      "type": "lstm",
      "bidirectional": true,
      "input_size": ${task_emb_size},
      "hidden_size": 100,
      "num_layers": 1,
      "dropout": 0.2
    },
    "similarity_function": {
      "type": "linear",
      "combination": "x,y,x*y",
      "tensor_1_dim": 200,
      "tensor_2_dim": 200
    },
    "modeling_layer": {
      "type": "lstm",
      "bidirectional": true,
      "input_size": 800,
      "hidden_size": 100,
      "num_layers": 2,
      "dropout": 0.2
    },
    "span_end_encoder": {
      "type": "lstm",
      "bidirectional": true,
      "input_size": 1400,
      "hidden_size": 100,
      "num_layers": 1,
      "dropout": 0.2
    },
    "dropout": 0.2
  },
  "iterator": {
    "type": "bucket",
    "sorting_keys": [["passage", "num_tokens"], ["question", "num_tokens"]],
    "batch_size": 40
  },

  "trainer": {
    "num_epochs": 20,
    "grad_norm": 5.0,
    "patience": 10,
    "validation_metric": "+em",
    "cuda_device": 0,
    "learning_rate_scheduler": {
      "type": "reduce_on_plateau",
      "factor": 0.5,
      "mode": "max",
      "patience": 2
    },
    "optimizer": {
      "type": "adam",
      "betas": [0.9, 0.9]
    }
  }
}
