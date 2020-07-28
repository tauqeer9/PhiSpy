#!/usr/bin/python3
__author__ = 'Przemek Decewicz'

import gzip
import sys
import pkg_resources
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from Bio import SeqIO
from PhiSpyModules import log_and_message, is_gzip_file
from compare_predictions_to_phages import genbank_seqio
from glob import glob
from os import makedirs, path
from numpy import arange
from subprocess import call

INSTALLATION_DIR = path.dirname(path.dirname(path.realpath(__file__)))

def read_genbank(gbkfile):

    """
    Parses GenBank file's CDSs and groups them into host or phage groups based on the '/is_phage' qualifier.
    Return lists of sequences of both of these groups.
    """

    log_and_message(f"Reading {gbkfile}.", stderr=True)

    infile_data = {
        'taxonomy': [],
        'bact_cds': [],
        'phage_cds': []
    }

    tax_present = False
    for record in genbank_seqio(gbkfile):
        # check records until taxonomy information is provided
        if not tax_present:
            if len(record.annotations['taxonomy']) == 0:
                infile_data['taxonomy'] = ['Bacteria']
            else:
                infile_data['taxonomy'] = record.annotations['taxonomy']
                tax_present = True

        # get bacteria and phage CDSs nucleotide sequences to make kmers
        for f in record.features:
            if f.type == 'CDS':
                dna = str(f.extract(record).seq)
                try:
                    status = f.qualifiers['is_phage'][0]
                    if status == '1':
                        infile_data['phage_cds'].append(dna)
                    else:
                        infile_data['bact_cds'].append(dna)
                except KeyError:
                    infile_data['bact_cds'].append(dna)
    if not tax_present:
        log_and_message(f"- WARNING! Taxonomy was missing!!! Assigning to Bacteria.", c="RED", stderr=True)
    log_and_message(f"- Bact CDSs: {len(infile_data['bact_cds'])}", stderr=True)
    log_and_message(f"- Phage CDSs: {len(infile_data['phage_cds'])}", stderr=True)

    return infile_data


def read_groups(infile, indir, training_data):

    """
    Reads tab-delimited input file with the path to input file to use for training in the first column
    (or just the file name if path provided with --indir) and the name of the group to put it afterwards
    while creating trainingGenome_list.txt.
    :param infile: path to the groups file
    :param indir: path to input directory with files indicated in group file
    :param training_data: dictionary with groups and infiles
    :return training_data: updated dictionary with genomes and infiles
    """

    trained_genomes = len(training_data['genomes'])
    trained_groups = len(training_data['groups'])

    with open(infile) as inf:
        for line in inf:
            line = line.strip().split('\t')
            infile = path.realpath(path.join(indir, line[0]))
            training_data['genomes'].add(infile)
            try:
                training_data['groups'][line[1]].add(infile)
            except KeyError:
                training_data['groups'][line[1]] = set([infile])

    log_and_message(f"Read {len(training_data['infiles']) - trained_genomes} new genomes assigned to {len(training_data['groups']) - trained_groups} new groups.", 
        stderr=True)

    return training_data


def read_kmers(infile):

    """
    Simply reads input file with kmers and returns set of read kmers.
    """

    kmers = []
    with open(infile) as inf:
        kmers = [x.strip() for x in inf.readlines()]

    return set(kmers)


def read_kmers_list(infile):

    """
    Simply reads input file with kmers and returns set of read kmers.
    """

    kmers = []
    with open(infile) as inf:
        kmers = [x.strip() for x in inf.readlines()]

    return kmers


def read_training_genomes_list():
    """
    Read trainingGenome_list.txt in PhiSpy's data directory and check currently set
    groups and already trained genomes.
    :return: training groups and genomes
    """

    log_and_message(f"Reading trainingGenome_list.txt file.", stderr=True)
    training_data = {'groups': {},
                     'genomes': set()}
    
    for line in pkg_resources.resource_stream('PhiSpyModules', 'data/trainingGenome_list.txt'):
        n, group, genomes, genomes_number = line.decode().strip().split('\t')
        genomes = set(genomes.split(';')) if ';' in genomes else set([genomes])
        training_data['groups'][group] = genomes
        training_data['genomes'].update(genomes)

    log_and_message(f"Read {len(training_data['genomes'])} genomes assigned to {len(training_data['groups'])} groups.", stderr=True)

    return training_data


def kmerize_orf(orf, k, t):

    """
    Creates kmers of size k and all, codon or simple type from a single input sequence.
    Return a set of identified unique kmers.
    """

    kmers = []
    if t == 'simple':
        stop = len(orf) - (len(orf) % k)
        for i in range(0, stop, k):
            kmers.append(orf[i : i + k])
    elif t == 'all':
        for j in range(0, k):
            stop = len(orf) - ((len(orf) - j) % k)
            for i in range(j, stop, k):
                kmers.append(orf[i : i + k])
    elif t == 'codon':
        for j in range(0, k, 3):
            stop = len(orf) - ((len(orf) - j) % k)
            for i in range(j, stop, k):
                kmers.append(orf[i : i + k])

    return kmers


def prepare_taxa_groups(infiles, training_data, retrain):
    """
    Reads all input files / genomes and creates a groups file based on all genomes taxonomy.
    :param infiles: all input files
    :param training_data: currently trained genomes and set groups
    :return training_data
    """

    log_and_message(f'Reading taxonomy information from {len(infiles)} input files.', c="PINK", stderr=True)
    for i, infile in enumerate(infiles, 1):
        file_name = path.basename(infile)
        if file_name not in training_data['genomes']:
            log_and_message(f"Processing {i}/{len(infiles)}: {file_name} (NEW)", c="YELLOW", stderr=True)

            infile_data = read_genbank(infile)
            for tax in infile_data['taxonomy']:
                try:
                    training_data['groups'][tax].add(infile)
                except KeyError:
                    training_data['groups'][tax] = set([infile])
        else:
            log_and_message(f"Skipping {i}/{len(infiles)}: {file_name} (already analyzed)", c="YELLOW", stderr=True)

        if file_name not in training_data['genomes'] or retrain:
            log_and_message(f"Preparing kmers files.")
            write_kmers_file(file_name, infile_data['bact_cds'], infile_data['phage_cds'], 12, 'all')


    log_and_message(f"Processed {len(infiles)} files.", c="PINK", stderr=True)

    return training_data


def update_training_genome_list(training_groups, new_training_groups):
    """
    Combines currently available training groups with those provided by user.
    """

    new_groups_cnt = 0
    upt_groupt_cnt = 0
    for group, infiles in new_training_groups.items():
        try:
            log_and_message(group, infiles)
            training_groups[group].update(set(map(path.basename,infiles)))
            upt_groupt_cnt += 1
        except KeyError:
            training_groups[group] = set(map(path.basename, infiles))
            new_groups_cnt += 1

    log_and_message(f'  Created {new_groups_cnt} new training groups.', stderr=True)
    log_and_message(f'  Updated {upt_groupt_cnt} training groups.', stderr=True)

    return training_groups


def write_kmers_file(file_name, bact_orfs_list, phage_orfs_list, kmer_size, kmers_type):
    """
    Calculates host/phage kmers from input file and writes phage-specific kmers to file.
    """

    MIN_RATIO = 1.0
    test_sets_dir = path.join(INSTALLATION_DIR, 'PhiSpyModules/data/testSets')
    if not path.isdir(test_sets_dir): makedirs(test_sets_dir)
    # host_kmers = set()
    # phage_kmers = set()
    kmers_dict = {} # {kmer: [# in host, # in phage]}
    kmers_total_count = 0
    kmers_host_unique_count = 0
    kmers_phage_unique_count = 0
    kmers_ratios = {}
    kmers_ratios_stats = {round(x, 2): 0 for x in arange(0, 1.01, 0.01)}
    kmers_ratios_file = path.join(test_sets_dir, f'{file_name}.kmers_ratios.txt')
    kmers_phage_file = path.join(test_sets_dir, f'{file_name}.kmers_phage.gz')
    kmers_host_file = path.join(test_sets_dir, f'{file_name}.kmers_host.gz')

    # kmrize CDSs
    for orf in bact_orfs_list:
        for kmer in kmerize_orf(orf, kmer_size, kmers_type):
            try:
                kmers_dict[kmer][0] += 1
            except KeyError:
                kmers_dict[kmer] = [1, 0]
                kmers_host_unique_count += 1
            kmers_total_count += 1
        # host_kmers.update(kmerize_orf(i, kmer_size, kmers_type))
    for orf in phage_orfs_list:
        for kmer in kmerize_orf(orf, kmer_size, kmers_type):
            try:
                kmers_dict[kmer][1] += 1
            except KeyError:
                kmers_dict[kmer] = [0, 1]
                kmers_phage_unique_count += 1
            kmers_total_count += 1
        # phage_kmers.update(kmerize_orf(i, kmer_size, kmers_type))

    log_and_message(f"Analyzed {kmers_total_count} kmers.", stderr=True)
    log_and_message(f"Identified {len(kmers_dict)} unique kmers.", stderr=True)
    log_and_message(f"- Bact unique {kmers_host_unique_count} ({kmers_host_unique_count / len(kmers_dict) * 100:.2f}%).", stderr=True)
    log_and_message(f"- Phage unique {kmers_phage_unique_count} ({kmers_phage_unique_count / len(kmers_dict) * 100:.2f}%).", stderr=True)

    ##################
    # the below part could be simplified if ratios will not be considered
    # it just slightly extends the calculations 
    ##################

    # calculate ratios
    for kmer, freqs in kmers_dict.items():
        ratio = round(freqs[1] / sum(freqs), 2)
        kmers_ratios[(ratio, kmer)] = freqs
        kmers_ratios_stats[ratio] += 1
    del kmers_dict

    # write ratios_stats
    log_and_message(f"Writing kmers ratios stats.", stderr=True)
    with open(kmers_ratios_file, 'w') as outf:
        outf.write("Ratio\tNumber of kmers\tPerc of such kmers\tCumulative perc\n")
        tot = 0
        tot_perc = 0
        for x in reversed(arange(0, 1.01, 0.01)):
            x = round(x, 2)
            tot += kmers_ratios_stats[x]
            perc = kmers_ratios_stats[x]/len(kmers_ratios) * 100
            tot_perc = tot / len(kmers_ratios) * 100
            outf.write(f"{x}\t{kmers_ratios_stats[x]}\t{perc:.3f}%\t{tot_perc:.3f}%\n")

    # write unique phage kmers
    log_and_message(f"Writing kmers into phage and host kmers files.", stderr=True)
    cnt = 0
    with gzip.open(kmers_phage_file, 'wt') as out_phage:
        with gzip.open(kmers_host_file, 'wt') as out_host:
            for ratio, kmer in kmers_ratios.keys():
                if ratio >= MIN_RATIO:
                    cnt += 1
                    out_phage.write(f"{kmer}\n")
                else:
                    out_host.write(f"{kmer}\n")
    log_and_message(f"- Wrote {cnt} kmers with ratios >= {MIN_RATIO}.", stderr=True)

    return


def write_training_genome_list(training_groups, training_genome_list_file):
    """
    Writes trainingGenome_list.txt file with currently available training sets.
    """

    group_cnt = 0
    with open(training_genome_list_file, 'w') as outf:
        for group, infiles in sorted(training_groups.items()):
            group_cnt += 1
            outf.write(f'{group_cnt}\t{group}\t{";".join(infiles)}\t{len(infiles)}\n')

    return


def main():
    args = ArgumentParser(prog = 'make_training_sets.py', 
                          description = 'Automates making new or extending current PhiSpy\'s training sets. By default these will be created in PhiSpyModules/data directory so keep that in mind preparing groups file. ',
                          epilog = 'Example usage:\npython3 scripts/make_training_sets.py -d test_genbank_files -o PhiSpyModules/data -g test_genbank_files/groups.txt --retrain --phmms pVOGs.hmm --color --threads 4',
                          formatter_class = RawDescriptionHelpFormatter)

    # args.add_argument('-i', '--infile',
    #                   type = str,
    #                   nargs = '*',
    #                   help = 'Path to input GenBank file(s). Multiple paths can be provided.')

    args.add_argument('-d', '--indir',
                      type = str,
                      help = 'Path to input directory with multiple GenBank files provided in groups file.')

    args.add_argument('-g', '--groups',
                      type = str,
                      help = 'Path to file with path to input file and its group name in two tab-delimited columns. Otherwise each file will have its own training set.')

    # args.add_argument('-o', '--outdir',
    #                   type = str,
    #                   help = 'Path to output directory. For each kmer creation approach subdirectory will be created.',
    #                   required = True)

    args.add_argument('--use_taxonomy',
                      action = 'store_true',
                      help = 'If set, taxonomy from input files will be used to update or create new groups. This is performed after reading groups file.')

    args.add_argument('-k', '--kmer_size',
                      type = int,
                      help = 'The size of required kmers. For codon approach use multiplicity of 3. [Default: 12]',
                      default = 12)

    args.add_argument('-t', '--kmers_type',
                      type = str,
                      help = 'Approach for creating kmers. Options are: simple (just slicing the sequence from the first position), all (all possible kmers), codon (all possible kmers made with step of 3 nts to get kmers corresponding translated aas). [Default: all]',
                      default = 'all')

    args.add_argument('--phmms',
                      type = str, 
                      help = 'Phage HMM profile database (like pVOGs) will be mapped against the genome of interest and used as additional feature to identify prophages.')

    args.add_argument('--color',
                      action = 'store_true',
                      help = 'If set, within the output GenBank file CDSs with phmms hits will be colored (for viewing in Artemis).')

    args.add_argument('--threads',
                      type = str,
                      help = 'Number of threads to use while searching with phmms.',
                      default = '4')

    args.add_argument('--skip_search',
                      action = 'store_true',
                      help = 'If set, the search part will be skipped and the program will assume the existance of updated GenBank files.')

    args.add_argument('--retrain',
                      action = 'store_true',
                      help = 'If set, retrains original training sets, otherwise it extends what it finds in output directory.')

    if len(sys.argv[1:]) == 0:
        args.log_and_message_help()
        args.exit()

    try:
        args = args.parse_args()
    except:
        args.exit()

    if not args.indir: 
        log_and_message(f"You have to provide input directory --indir.", c="RED",
                        stderr=True, stdout=False)
        sys.exit(2)

    # Create output directory
    #if not path.isdir(args.outdir): makedirs(args.outdir)



    # Retrain everything or just extend the reference sets
    if not args.retrain:
        # new_infiles = set()
        # for infile in infiles:
        #     if path.basename(infile) in training_genomes:
        #         continue
        #     else:
        #         new_infiles.add(infile)
        # infiles = new_infiles
        log_and_message(f'Running in a regular mode: training sets will be extended.', c="GREEN", stderr=True)
    else:
        log_and_message(f'Running in a retrain mode: recreating all trainSets.', c="GREEN", stderr=True)

    # read currently available genomes - either by reading trainingGenome_list.txt or trainSets directory
    log_and_message("Checking currently available training sets.", c="GREEN", stderr=True, stdout=False)
    #training_genome_list_file = path.join(args.outdir, 'trainingGenome_list.txt')
    if pkg_resources.resource_exists('PhiSpyModules', 'data/trainingGenome_list.txt'):
        training_data = read_training_genomes_list()
    else:
        log_and_message(f"{training_genome_list_file} is missing.", c="RED", stderr=True)
        training_data = {'groups': {}, 'genomes': set()}


    # groups of resulting training sets
    if args.groups:
        log_and_message(f"Reading provided groups file.", c="GREEN", stderr=True)
        training_data = read_groups(args.groups, args.indir, args.retrain)


    if args.use_taxonomy:
        log_and_message(f"Using taxonomy from input files to create new or update current groups.", c="GREEN", stderr=True)
        infiles = glob(path.join(args.indir, r'*.gb'))
        infiles += glob(path.join(args.indir, r'*.gb[kf]'))
        infiles += glob(path.join(args.indir, r'*.gbff'))
        infiles += glob(path.join(args.indir, r'*.gb.gz'))
        infiles += glob(path.join(args.indir, r'*.gb[kf].gz'))
        infiles += glob(path.join(args.indir, r'*.gbff.gz'))
        infiles = set(infiles)
        training_data = prepare_taxa_groups(infiles, training_data, args.retrain)
    exit()


    # make sure all output directories are present
    trainsets_outdir = path.join('PhiSpyModules', 'data')
    if not path.isdir(trainsets_outdir): makedirs(trainsets_outdir)

    for infile in infiles:
        log_and_message(f'Making trainSet for {path.basename(infile)}.', stderr=True)

        kmers_file = write_kmers_file(infile, trainsets_outdir, args.kmer_size, args.kmers_type)

        cmd = ['PhiSpy.py', infile, '-o', trainsets_outdir, '-m', path.basename(infile) + '.trainSet', '--kmer_size', str(args.kmer_size), '--kmers_type', args.kmers_type, '--kmers_file', kmers_file]
        if args.phmms: cmd.extend(['--phmms', args.phmms, '-t', args.threads])
        if args.color: cmd.append('--color')
        if args.skip_search: cmd.append('--skip_search')
        log_and_message(f'Calling PhiSpy to make a trainSet.', stderr=True)
        log_and_message(f'Command: {" ".join(cmd)}', stderr=True)
        log_and_message(f'{"PhiSpy start":=^30s}', stderr=True)
        log_and_message(cmd, stderr=True)
        log_and_message(f'{"PhiSpy stop":=^30s}\n', stderr=True)

    # update trainingGenome_list file = this is a new groups file for genomes available in PhiSpy's data directory
    log_and_message('Updating trainingGenome_list.', stderr=True)
    training_groups = update_training_genome_list(training_groups, new_training_groups)


    # write updated training groups
    log_and_message('Writing updated trainingGenome_list.', stderr=True)
    write_training_genome_list(training_groups, training_genome_list_file)

    log_and_message('Done!', stderr=True)

if __name__ == '__main__':
    main()
