#!/bin/bash
#SBATCH --account=rrg-dprecup
#SBATCH --ntasks=1
#SBATCH --mem=30000M
#SBATCH --mail-type=ALL
#SBATCH --mail-user=kushal.arora@mail.mcgill.ca
#SBATCH --time=23:00:00
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
###########################

set -ex
echo $(date '+%Y_%m_%d_%H_%M') - $SLURM_JOB_NAME - $SLURM_JOBID - `hostname` - ${output_dir} >> ./lm_wn_machine_assignments-v2.txt
source activate lm_wn

export emb_size="${emb_size:=300}"
export wnhid="${wnhid:=100}"
export nhid="${nhid:=300}"
export distance="${distance:=cosine}"
export task_emb_size=${emb_size}
export log_interval=${log_interval:=200}

cmd="python -u main.py --cuda --save-emb ${output_dir} --save ${output_dir} "

if [ -n "$log_interval" ]; then
   cmd+=" --log-interval ${log_interval} "
fi

if [ -n "$lr" ]; then
    cmd+=" --lr $lr"
fi

if [ -n "$epoch" ]; then
    cmd+=" --epoch $epoch"
fi

if [ -n "$bptt" ]; then
    cmd+=" --bptt $bptt"
fi

if [ -n "$bsize" ]; then
    cmd+=" --batch-size $bsize"
fi

if [ -n "$patience" ]; then
    cmd+=" --patience $patience"
fi

if [ -n "$emb_size" ]; then
    cmd+=" --emsize $emb_size"
fi

if [ -n "$nhid" ]; then
    cmd+=" --nhid $nhid"
fi

if [ -n "$wnhid" ]; then
    cmd+=" --wn_hid $wnhid"
fi

if [ -n "$data" ]; then
    cmd+=" --data $data"
fi

if [ -n "$optim" ]; then
    cmd+=" --optim $optim"
fi

if [ -n "$distance" ]; then
    cmd+=" --distance $distance"
fi

if [ -n "$reg" ]; then
    cmd+=" --reg"
fi

if [ -n "$tied" ]; then
    cmd+=" --tied"
fi

if [ -n "$adaptive" ]; then
    cmd+=" --adaptive"
fi

if [ -n "$nce" ]; then
    cmd+=" --nce"
fi

if [ -n "$extend_wn" ]; then
    cmd+=" --extend_wn"
fi

if [ -n "$syn" ]; then
    cmd+=" -l syn"
    if [ -n "$extend_wn" ]; then
        task_emb_size=`expr ${task_emb_size} + ${wnhid}`
    fi
fi

if [ -n "$hyp" ]; then
    cmd+=" -l hyp"
    if [ -n "$extend_wn" ]; then
        task_emb_size=`expr ${task_emb_size} + ${wnhid}`
    fi
fi

if [ -n "$mer" ]; then
    cmd+=" -l mer"
    if [ -n "$extend_wn" ]; then
        task_emb_size=`expr ${task_emb_size} + ${wnhid}`
    fi
fi

if [ -n "$seg" ]; then
    cmd+=" --seg"
fi

if [ -n "$fixed_wn" ]; then
    cmd+=" --fixed_wn"
fi

if [ -n "$random_wn" ]; then
    cmd+=" --random_wn"
fi

if [ -n "$lower" ]; then
    cmd+=" --lower"
fi

if [ -n "$mdl" ]; then
    cmd+=" --model $mdl"
fi

if [ -n "$adir" ]; then
    cmd+=" --annotated_dir $adir "
fi

if [ -n "${nlayers}" ]; then
    cmd+=" --nlayers ${nlayers} "
fi

if [ ${wn_ratio} ]; then
    cmd+=" --wn_ratio ${wn_ratio}"
fi

if [ -z "${step}" ]; then
    step=1
fi

step_till=${step_till:=100}
echo ${step_till}

if [ -z "${emb_filename}" ]; then
    emb_filename=emb_${data}_${mdl}_${lexs}_${emb_size}_${nhid}_${wnhid}_${distance}
fi

export emb_filetxt=${output_dir}/${emb_filename}.txt
export bidaf_input_size=$(expr ${task_emb_size} + 100)
export ner_input_size=$(expr ${task_emb_size} + 128)

declare -A task2time
task2time["ner"]="3:00:00"
task2time["sst"]="01:00:00"
task2time["esim"]="8:00:00"
task2time["bidaf"]="6:00:00"

run_extrinsic_task () {
    task=$1
    task_file=$(mktemp ${output_dir}/${task}-${emb_filename}.XXXXXX)
    envsubst < ./extrinsic_tasks/local/${task}_template.jsonnet > ${task_file}
    sbatch -o ${output_dir}/${task}_std.out \
        -J "${task}_${SLURM_JOB_NAME}" \
        -e ${output_dir}/${task}_std.out \
        -A ${account} \
        -t "${task2time[$task]}" \
        scripts/launcher_basic.sh allennlp train ${task_file} -s ${output_dir}/${task}/
}

if [ ${step} -lt 2 ]; then
    $cmd
    step=`expr ${step} + 1`

    if [ ${step} -gt ${step_till} ]; then
        exit 1;
    fi
fi

i=3
for ext_task in ner sst esim bidaf
do
    if [ ${step} -lt ${i} ]; then
        run_extrinsic_task ${ext_task};
        step=`expr ${step} + 1`
    fi
    i=`expr ${i} + 1`

    if [ ${step} -gt ${step_till} ]; then
        exit 1;
    fi
done

if [ ${step} -lt 7 ]; then
    cd analogy_tasks;
    python main.py  --sim-task --emb ../${output_dir}/${emb_filename}.pkl --vocab ../${output_dir}/vocab_${data}.pkl
    step=`expr ${step} + 1`
    cd -;

    if [ ${step} -gt ${step_till} ]; then
        exit 1;
    fi
fi


if [ ${step} -lt 8 ]; then

    cd analogy_tasks;
    if [ -n "${syn}" ]; then
        emb_syn_filename1="../${output_dir}/emb_syn_${data}_${mdl}_${lexs}_${emb_size}_${nhid}_${wnhid}_${distance}.pkl"
        emb_syn_filename2="../${output_dir}/emb_syn_${data}_${mdl}_${lexs}_${emb_size}_${nhid}_${wnhid}_${distance}.pkl"
        python main.py --sim-task --emb ${emb_syn_filename1} --emb2 ${emb_syn_filename2} --vocab  ../${output_dir}/vocab_${data}.pkl --prefix syn
    fi

    if [ -n "${hyp}" ]; then
        emb_hyp_filename1="../${output_dir}/emb_hypn_hyponyms_${data}_${mdl}_${lexs}_${emb_size}_${nhid}_${wnhid}_${distance}.pkl"
        emb_hyp_filename2="../${output_dir}/emb_hypn_hypernyms_${data}_${mdl}_${lexs}_${emb_size}_${nhid}_${wnhid}_${distance}.pkl"
        python main.py --sim-task --emb ${emb_hyp_filename1} --emb2 ${emb_hyp_filename2} --vocab  ../${output_dir}/vocab_${data}.pkl --prefix hyp
    fi

    if [ -n "${mer}" ]; then
        emb_mer_filename1="../${output_dir}/emb_mern_meronyms_${data}_${mdl}_${lexs}_${emb_size}_${nhid}_${wnhid}_${distance}.pkl"
        emb_mer_filename2="../${output_dir}/emb_mern_holonyms_${data}_${mdl}_${lexs}_${emb_size}_${nhid}_${wnhid}_${distance}.pkl"
        python main.py --sim-task --emb ${emb_mer_filename1} --emb2 ${emb_mer_filename2} --vocab  ../${output_dir}/vocab_${data}.pkl --prefix mer
    fi
    cd -;
fi
