# coding: utf-8
import argparse
import hashlib
import math
import os
import numpy as np
import time
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.onnx
import _pickle as pickle
# from tqdm import tqdm

import model

import csv
csv.field_size_limit(100000000)

from torchtext import data, datasets
import torchtext
import csv
csv.field_size_limit(100000000)

parser = argparse.ArgumentParser(description='PyTorch Wikitext-2 RNN/LSTM Language Model')
parser.add_argument('--data', type=str, default='wikitext-2',
                    help='location of the data corpus')
parser.add_argument('--model', type=str, default='LSTM',
                    help='type of recurrent net (RNN_TANH, RNN_RELU, LSTM, GRU)')
parser.add_argument('--lex', '-l', action="append", type=str, default=[], dest='lex_rels',
                    help='list of type of lexical relations to capture. Options | syn | hyp | mer')
parser.add_argument('--emsize', type=int, default=300,
                    help='size of word embeddings')
parser.add_argument('--nhid', type=int, default=300,
                    help='number of hidden units per layer')
parser.add_argument('--wn_hid', type=int, default=100,
                    help='Dimension of the WN subspace')
parser.add_argument('--margin', type=int, default=1,
                    help='define the margin for the max-margin loss')
parser.add_argument('--patience', type=int, default=1,
                    help='How long before you reduce the LR.')
parser.add_argument('--nlayers', type=int, default=2,
                    help='number of layers')
parser.add_argument('--lr', type=float, default=0.001,
                    help='initial learning rate')
parser.add_argument('--clip', type=float, default=0.25,
                    help='gradient clipping')
parser.add_argument('--epochs', type=int, default=14,
                    help='upper epoch limit')
parser.add_argument('--batch-size', type=int, default=20, metavar='N',
                    help='batch size')
parser.add_argument('--bptt', type=int, default=35,
                    help='sequence length')
parser.add_argument('--dropout', type=float, default=0.2,
                    help='dropout applied to layers (0 = no dropout)')
parser.add_argument('--tied', action='store_true',
                    help='tie the word embedding and softmax weights')
parser.add_argument('--seed', type=int, default=1111,
                    help='random seed')
parser.add_argument('--cuda', action='store_true',
                    help='use CUDA')
parser.add_argument('--retro', action='store_true',
                    help='use retrofitting')
parser.add_argument('--gpu', type=int, default=0,
                    help='use gpu x')
parser.add_argument('--log-interval', type=int, default=200, metavar='N',
                    help='report interval')
parser.add_argument('--save', type=str, default='models/',
                    help='path to save the final model')
parser.add_argument('--save-emb', type=str, default='embeddings/',
                    help='path to save the final model')
parser.add_argument('--onnx-export', type=str, default='',
                    help='path to export the final model in onnx format')
parser.add_argument('--adaptive', action='store_true',
                    help='Use adaptive softmax. This speeds up computation.')
parser.add_argument('--wn_ratio', type=float, default=0.2,
                    help='dropout applied to layers (0 = no dropout)')
parser.add_argument('--distance', type=str, default='pairwise',
                    help='Type of distance to use. Options are [pairwise, cosine]')
parser.add_argument('--optim', type=str, default='sgd',
                    help='Type of optimizer to use. Options are [sgd, adam]')
parser.add_argument('--reg', action='store_true', help='Regularize.')
parser.add_argument('--seg', action='store_true', help='Segregated WN and LM model.')
parser.add_argument('--fixed_wn', action='store_true', help='Fixed WN proj matrices to identity matrix.')
parser.add_argument('--random_wn', action='store_true', help='Fix random WN proj matrix and not learn it.')
args = parser.parse_args()

# Set the random seed manually for reproducibility.
torch.manual_seed(args.seed)
if torch.cuda.is_available():
    if not args.cuda:
        print("WARNING: You have a CUDA device, so you should probably run with --cuda")

device = torch.device("cuda:" + str(args.gpu) if args.cuda else "cpu")

class Dataset(data.TabularDataset):
    def __init__(self, dataset, fields):
       super(Dataset, self).__init__(dataset, 'json', fields=fields)

    @classmethod
    def splits(cls, fields, dataset_dir=None, train_file=None, valid_file=None, test_file=None, **kwargs):
        if dataset_dir:
            train_file = train_file or os.path.join(dataset_dir, 'train.txt')
            valid_file = valid_file or os.path.join(dataset_dir, 'valid.txt')
            test_file = test_file or os.path.join(dataset_dir, 'test.txt')

        return (cls(train_file, fields, **kwargs),
                cls(valid_file, fields, **kwargs),
                cls(test_file, fields, **kwargs))

    @classmethod
    def iters(cls, dataset_dir=None, train_file=None, valid_file=None, test_file=None,
                device=-1, batch_size=args.batch_size, load_from_file=False, version=1, **kwargs):

        def preprocessing(prop_list):
            if len(prop_list) == 0:
                return ['<pad>', '<pad>']
            return [x.split(',') for x in prop_list]

        TEXT_FIELD = data.Field(batch_first=False, include_lengths=False)
        WORDNET_TEXT_FIELD = data.Field(fix_length=2)
        field_dict = {
                'text': ('text', TEXT_FIELD),
                'target': ('target', TEXT_FIELD),
                'synonyms': ('synonyms', data.NestedField(WORDNET_TEXT_FIELD, preprocessing=preprocessing)),
                'antonyms': ('antonyms', data.NestedField(WORDNET_TEXT_FIELD, preprocessing=preprocessing)),
                'hypernyms': ('hypernyms', data.NestedField(WORDNET_TEXT_FIELD, preprocessing=preprocessing)),
                'meronyms': ('meronyms', data.NestedField(WORDNET_TEXT_FIELD, preprocessing=preprocessing))
                }
        suffix = hashlib.md5('{}-{}-{}-{}-{}'.format(version, dataset_dir,
                                                     train_file, valid_file, test_file)
                                            .encode()).hexdigest()

        examples_path = os.path.join(dataset_dir, '{}.pkl'.format(suffix))

        save_iters = False
        if not load_from_file:
            try:
                examples = torch.load(examples_path)
            except:
                load_from_file = True
                save_iters = True

        if load_from_file:
                dataset = cls.splits(field_dict, dataset_dir, train_file, valid_file, test_file, **kwargs)
                if save_iters:
                    torch.save([d.examples for d in dataset], examples_path)

        if not load_from_file:
            dataset = [data.Dataset(ex, field_dict.values()) for ex in examples]

        train, valid, test = dataset

        vec = torchtext.vocab.Vectors('glove.6B.300d.txt', cache='data/glove')
        if not args.retro:
            TEXT_FIELD.build_vocab(train)
        else:
            vec = torchtext.vocab.Vectors('glove.6B.300d.txt', cache='data/glove')
            TEXT_FIELD.build_vocab(train, vectors=vec)
        WORDNET_TEXT_FIELD.vocab = TEXT_FIELD.vocab

        train_iter, valid_iter, test_iter = data.Iterator.splits((train, valid, test),
                                                batch_size=batch_size, device=device,
                                                shuffle=False, repeat=False, sort=False)
        if args.retro:
            return train_iter, valid_iter, test_iter, TEXT_FIELD.vocab, TEXT_FIELD.vocab.vectors
        else:
            return train_iter, valid_iter, test_iter, TEXT_FIELD.vocab
dist_fn = lambda x1,x2: 1 - F.cosine_similarity(x1,x2) if args.distance == 'cosine' else F.pairwise_distance(x1,x2)

if args.retro:
    train_iter, valid_iter, test_iter, vocab, pretrained = Dataset.iters(dataset_dir=os.path.join('./data', args.data, 'annotated_{}_{}'.format(args.bptt, args.batch_size)), device=device)
else:
    train_iter, valid_iter, test_iter, vocab = Dataset.iters(dataset_dir=os.path.join('./data', args.data, 'annotated_{}_{}'.format(args.bptt, args.batch_size)), device=device)
# This is the default WikiText2 iterator from TorchText.
# Using this to compare our iterator. Will delete later.
# train_iter, valid_iter, test_iter = datasets.WikiText103.iters(batch_size=args.batch_size, bptt_len=args.bptt,
                                                             # device=device, root=args.data)
# vocab = train_iter.dataset.fields['text'].vocab

ntokens = len(vocab)
pad_idx = vocab.stoi['<pad>']


lr = args.lr
best_val_loss = None

def repackage_hidden(h):
    """Wraps hidden states in new Tensors, to detach them from their history."""
    if isinstance(h, torch.Tensor):
        return h.detach()
    else:
        return tuple(repackage_hidden(v) for v in h)

cutoffs = [100, 1000, 5000] if args.data == 'wikitext-2' else [2800, 20000, 76000]

if args.seg:
    lm_model = model.RNNModel(args.model, ntokens, args.emsize, args.nhid, args.nlayers, args.dropout, args.tied, args.adaptive).to(device)
    wn_model = model.WNModel(lm_model.encoder, args.emsize, args.wn_hid,
                             antonym_margin=args.margin,
                             fixed=args.fixed_wn,
                             random=args.random_wn).to(device)
    model = model.WNLM(lm_model, wn_model).to(device)
elif args.retro:
    gl_model = model.GloveEncoderModel(ntokens, args.emsize, pretrained).to(device)
    wn_model = model.WNModel(gl_model.encoder, args.emsize, args.wn_hid,
                             antonym_margin=args.margin,
                             fixed=args.fixed_wn,
                             random=args.random_wn).to(device)
    model = model.GloveModel(gl_model, wn_model).to(device)
else:
    model = model.RNNWordnetModel(args.model, ntokens, args.emsize, args.nhid, args.nlayers, args.wn_hid, args.dropout, args.tied, args.adaptive, cutoffs).to(device)

criterion = nn.NLLLoss()

optimizer = torch.optim.Adam(model.parameters(), lr=lr) if args.optim == 'adam' else torch.optim.SGD(model.parameters(), lr=lr)
milestones=[4,6,8] if args.data == 'wikitext-103' else [10, 25, 35, 45]
scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, milestones=milestones)

pickle.dump(vocab, open('vocab_' + str(args.data) + '.pkl', 'wb'))
print('Vocab Saved')

print('Lex Rel List: {}'.format(args.lex_rels))
def evaluate(data_source):
    # Turn on evaluation mode which disables dropout.
    model.eval()
    total_loss = 0.
    total_loss_syn = 0.
    total_loss_ant = 0.
    total_loss_hyp = 0.
    total_loss_mern = 0.
    if not args.retro:
        hidden = model.init_hidden(args.batch_size)
    start_time = time.time()
    with torch.no_grad():
        for i, batch in enumerate(data_source):


            data, targets = batch.text, batch.target
            synonyms, antonyms, hypernyms, meronyms = batch.synonyms, batch.antonyms, batch.hypernyms, batch.meronyms

            if not args.retro:
                output_dict = model(data, hidden, targets, synonyms, antonyms, hypernyms, meronyms)
                output, hidden = output_dict['log_probs'], output_dict['hidden_vec']
                output = output.view(-1, ntokens)
                targets = targets.view(-1)
                hidden = repackage_hidden(hidden)

                loss = output_dict.get('loss_lm', criterion(output, targets))

            else:
                output_dict = model(data, synonyms, antonyms, hypernyms, meronyms)
                emb, emb_glove = output_dict['glove_emb']
                loss = output_dict.get('glove_loss',
                                        torch.mean(dist_fn(emb, emb_glove)))
            total_loss += loss
            if 'syn' in args.lex_rels:
                emb_syn1, emb_syn2 = output_dict['syn_emb']
                loss_syn = output_dict.get('loss_syn',
                                            torch.mean(dist_fn(emb_syn1, emb_syn2)))
                total_loss_syn += loss_syn

                emb_ant1, emb_ant2 = output_dict['ant_emb']
                loss_ant = output_dict.get('loss_ant',
                                            torch.mean(F.relu(args.margin - dist_fn(emb_ant1, emb_ant2))))
                total_loss_ant += loss_ant

            if 'hyp' in args.lex_rels:
                if 'loss_hyp' in output_dict:
                    loss_hyp = output_dict['loss_hyp']
                else:
                    emb_hyp1, emb_hyp2 = output_dict['hyp_emb']
                    hyp_mask = 1 - (hypernyms[:,0] == pad_idx).unsqueeze(1).expand(-1, args.wn_hid).float()
                    hyp_len = torch.sum(1 - (hypernyms[:,0] == pad_idx).float())
                    emb_hyp1, emb_hyp2 = (emb_hyp1 * hyp_mask, emb_hyp2 * hyp_mask)
                    loss_hyp = torch.mean(dist_fn(emb_hyp1, emb_hyp2))

                total_loss_hyp += loss_hyp

            if 'mer' in args.lex_rels:
                if 'loss_mer' in output_dict:
                    loss_mer = output_dict['loss_mer']
                else:
                    emb_mern1, emb_mern2 = output_dict['mer_emb']
                    mer_mask = 1 - (meronyms[:,0] == pad_idx).unsqueeze(1).expand(-1, args.wn_hid).float()
                    mer_len = torch.sum(1 - (meronyms[:,0] == pad_idx).float())
                    emb_mern1, emb_mern2 = (emb_mern1 * mer_mask, emb_mern2 * mer_mask)
                    loss_mer = torch.mean(dist_fn(emb_mern1, emb_mern2))

                total_loss_mern += loss_mer

    return total_loss/(len(data_source) - 1), total_loss_syn/(len(data_source) - 1), total_loss_ant/(len(data_source) - 1), \
            total_loss_hyp/ (len(data_source) - 1), total_loss_mern/(len(data_source) - 1)


def train():
    # Turn on training mode which enables dropout.
    model.train()
    total_loss_ = 0.
    total_loss_hyp = 0.
    total_loss_syn = 0.
    total_loss_ant = 0.
    total_loss_mern = 0.
    total_loss_reg = 0.
    start_time = time.time()
    if not args.retro:
        hidden = model.init_hidden(args.batch_size)
    for idx, batch in enumerate(train_iter):
        data, targets = batch.text, batch.target
        synonyms, antonyms, hypernyms, meronyms = batch.synonyms, batch.antonyms, batch.hypernyms, batch.meronyms
        synonyms = synonyms.view(-1, 2)
        antonyms = antonyms.view(-1, 2)
        hypernyms = hypernyms.view(-1, 2)
        meronyms = meronyms.view(-1, 2)

        optimizer.zero_grad()

        if not args.retro:
            output_dict = model(data, hidden, targets, synonyms, antonyms, hypernyms, meronyms)

            output, hidden = output_dict['log_probs'], output_dict['hidden_vec']
            output = output.view(-1, ntokens)
            targets = targets.view(-1)
            hidden = repackage_hidden(hidden)

            loss = output_dict.get('loss_lm', criterion(output, targets))
        else:
            output_dict = model(data, synonyms, antonyms, hypernyms, meronyms)
            emb, emb_glove = output_dict['glove_emb']
            loss = output_dict.get('glove_loss',
                                    torch.mean(dist_fn(emb, emb_glove)))
        total_loss = loss

        if 'syn' in args.lex_rels:
            emb_syn1, emb_syn2 = output_dict['syn_emb']
            loss_syn = output_dict.get('loss_syn',
                                        torch.mean(dist_fn(emb_syn1, emb_syn2)))

            emb_ant1, emb_ant2 = output_dict['ant_emb']
            loss_ant = output_dict.get('loss_ant',
                                        torch.mean(F.relu(args.margin - dist_fn(emb_ant1, emb_ant2))))

            total_loss += loss_syn + loss_ant
            total_loss_syn += loss_syn.item()
            total_loss_ant += loss_ant.item()

        if 'hyp' in args.lex_rels:
            if 'loss_hyp' in output_dict:
                loss_hyp = output_dict['loss_hyp']
            else:
                emb_hyp1, emb_hyp2 = output_dict['hyp_emb']
                hyp_mask = 1 - (hypernyms[:,0] == pad_idx).unsqueeze(1).expand(-1, args.wn_hid).float()
                hyp_len = torch.sum(1 - (hypernyms[:,0] == pad_idx).float())
                emb_hyp1, emb_hyp2 = (emb_hyp1 * hyp_mask, emb_hyp2 * hyp_mask)
                loss_hyp = torch.mean(dist_fn(emb_hyp1, emb_hyp2))

            total_loss += loss_hyp
            total_loss_hyp += loss_hyp.item()

        if 'mer' in args.lex_rels:
            if 'loss_mer' in output_dict:
                loss_mer = output_dict['loss_mer']
            else:
                emb_mern1, emb_mern2 = output_dict['mer_emb']
                mer_mask = 1 - (meronyms[:,0] == pad_idx).unsqueeze(1).expand(-1, args.wn_hid).float()
                mer_len = torch.sum(1 - (meronyms[:,0] == pad_idx).float())
                emb_mern1, emb_mern2 = (emb_mern1 * mer_mask, emb_mern2 * mer_mask)
                loss_mer = torch.mean(dist_fn(emb_mern1, emb_mern2))

            total_loss += loss_mer
            total_loss_mern += loss_mer.item()

        if args.reg:
            reg_loss = output_dict.get('reg_loss', 0)
            total_loss_reg = reg_loss
            total_loss += reg_loss

        total_loss.backward()

        # `clip_grad_norm` helps prevent the exploding gradient problem in RNNs / LSTMs.
        torch.nn.utils.clip_grad_norm_(model.parameters(), args.clip)
        optimizer.step()

        total_loss_ += loss.item()

        if idx % args.log_interval == 0 and idx > 0:
            cur_loss = total_loss_ / args.log_interval
            curr_syn_loss = total_loss_syn / args.log_interval
            curr_ant_loss = total_loss_ant / args.log_interval
            curr_hyp_loss = total_loss_hyp / args.log_interval
            curr_mern_loss = total_loss_mern / args.log_interval
            curr_reg_loss = total_loss_reg / args.log_interval

            elapsed = time.time() - start_time
            print('| epoch {:3d} | {:5d}/{:5d} batches | lr {:02.10f} | ms/batch {:5.2f} | loss {:5.2f} | ppl {:8.2f} | syn loss {:5.2f} | ant loss {:5.2f} | hyp loss {:5.2f} | mer loss {:5.2f} | reg_loss {:5.2f}'
                    .format(epoch, idx, len(train_iter), optimizer.param_groups[0]['lr'], elapsed * 1000 / args.log_interval,
                        cur_loss, math.exp(cur_loss), curr_syn_loss, curr_ant_loss, curr_hyp_loss, curr_mern_loss, curr_reg_loss))
            start_time = time.time()
            total_loss_ = 0
            total_loss_syn = 0
            total_loss_ant = 0
            total_loss_hyp = 0
            total_loss_mern = 0

    print()

patience = 0
lex_rels = '_'.join(args.lex_rels)
model_name = os.path.join(args.save, 'model_' + args.data + '_' + lex_rels + '_' + str(args.emsize) + '_' + str(args.nhid) + '_' + str(args.wn_hid) + '_' + args.distance + '_' + str(args.retro)  + '.pt')
emb_name = os.path.join(args.save_emb, 'emb_' + args.data + '_' + lex_rels + '_' + str(args.emsize) + '_' + str(args.nhid) + '_' + str(args.wn_hid) + '_' + args.distance + '_' + str(args.retro) + '.pkl')
emb_name_txt = os.path.join(args.save_emb, 'emb_' + args.data + '_' + lex_rels + '_' + str(args.emsize) + '_' + str(args.nhid) + '_' + str(args.wn_hid) + '_' + args.distance + '_' + str(args.retro) + '.txt')

try:
    for epoch in range(1, args.epochs+1):
        epoch_start_time = time.time()
        train()
        if not args.retro:
            val_loss, loss_syn, loss_ant, loss_hyp, loss_mer = evaluate(valid_iter)
            print('-' * 89)
            print('| end of epoch {:3d} | time: {:5.2f}s | valid loss {:5.2f} | valid ppl {:8.2f} | syn loss {:5.2f} | ant loss {:5.2f} | hyp loss {:5.2f} | mer loss {:5.2f}'
                        .format(epoch, (time.time() - epoch_start_time), val_loss, math.exp(val_loss),
                                        loss_syn, loss_ant, loss_hyp, loss_mer))
            print('-' * 89)
            # Save the model if the validation loss is the best we've seen so far.
            if not best_val_loss or val_loss < best_val_loss:
                with open(model_name, 'wb') as f:
                    torch.save(model, f)
                print('Saving learnt embeddings : %s' % emb_name)
                pickle.dump(model.encoder.weight.data, open(emb_name, 'wb'))

                best_val_loss = val_loss
                patience = 0
            else:
                patience += 1
            scheduler.step()
            if False and patience > 3:
                break
        else:
            with open(model_name, 'wb') as f:
                torch.save(model, f)
            print('Saving learnt embeddings : %s' % emb_name)
            pickle.dump(model.encoder.weight.data.cpu().numpy(), open(emb_name, 'wb'))
except KeyboardInterrupt:
    print('-' * 89)
    print('Exiting from training early')

# Load the best saved model.
with open(model_name, 'rb') as f:
    model = torch.load(f)
    # after load the rnn params are not a continuous chunk of memory
    # this makes them a continuous chunk, and will speed up forward pass
    model.rnn.flatten_parameters()


# Run on test data.
if not args.retro:
    test_loss, test_syn, test_ant, test_hyp, test_mer = evaluate(test_iter)
    print('=' * 89)
    print('| End of training | test loss {:5.2f} | test ppl {:8.2f} | syn loss {:5.2f} | ant loss {:5.2f} | hyp loss {:5.2f} | mer loss {:5.2f}'.format(
        test_loss, math.exp(test_loss), test_syn, test_ant, test_hyp, test_mer))
    print('=' * 89)
print('Saving final learnt embeddings ')
pickle.dump(model.encoder.weight.data, open(emb_name, 'wb'))
with open(emb_name_txt, 'w') as f:
    final_emb = model.encoder.weight.data.cpu().numpy()
    for i in range(final_emb.shape[0]):
        f.write(vocab.itos[i] + ' ')
        f.write(' '.join([str(x) for x in final_emb[i, :]]) + '\n')

# if len(args.onnx_export) > 0:
#     # Export the model in ONNX format.
#     export_onnx(args.onnx_export, batch_size=1, seq_len=args.bptt)
