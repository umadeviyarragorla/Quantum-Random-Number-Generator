"""
MODULE-2 : QRNG vs RNG COMPARISON
---------------------------------
Trials: 20
Bits per trial: 1,000,000
"""

import os
import sqlite3
import numpy as np
import math
import random
import time
import secrets
from datetime import datetime
from dotenv import load_dotenv
from scipy.stats import chisquare

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from qrng.quantum_rng import (
    set_provider_as_IBMQ,
    set_backend_interactive,
    get_backend_name,
    get_bit_string
)

from randomness_testsuite.FrequencyTest import FrequencyTest
from randomness_testsuite.RunTest import RunTest
from randomness_testsuite.ApproximateEntropy import ApproximateEntropy
from randomness_testsuite.Serial import Serial
from randomness_testsuite.Spectral import SpectralTest
from randomness_testsuite.CumulativeSum import CumulativeSums
from randomness_testsuite.Matrix import Matrix
from randomness_testsuite.Complexity import ComplexityTest


DB_FILE="results.db"
TABLE="final_results"


# =========================================================
# DATABASE
# =========================================================

def db_setup():

    conn=sqlite3.connect(DB_FILE,timeout=30)
    cur=conn.cursor()

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE}(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT,
    rng TEXT,
    backend TEXT,
    trials INTEGER,
    bits_per_trial INTEGER,
    avg_entropy REAL,
    avg_min_entropy REAL,
    avg_collision_entropy REAL,
    avg_bias REAL,
    avg_autocorrelation REAL,
    avg_zeros REAL,
    avg_ones REAL,
    avg_freq_p REAL,
    avg_runs_p REAL,
    avg_apen_p REAL,
    avg_serial_p REAL,
    avg_fft_p REAL,
    avg_cusum_p REAL,
    avg_matrix_p REAL,
    avg_complexity_p REAL,
    nist_pass_rate REAL,
    chi_square_p REAL,
    predictability REAL,
    avg_generation_time REAL
    )
    """)

    conn.commit()
    conn.close()


# =========================================================
# RNG IMPLEMENTATIONS
# =========================================================

def seed_prng():
    random.seed(int.from_bytes(os.urandom(8),"big"))


def get_prng_bits(n):
    return "".join(str(random.getrandbits(1)) for _ in range(n))


def get_secrets_bits(n):
    return "".join(str(secrets.randbits(1)) for _ in range(n))


def get_urandom_bits(n):
    data=os.urandom(n)
    return "".join(format(b,"08b") for b in data)[:n]


# ---------- LCG (weak RNG)

def get_lcg_bits(n):

    a=1664525
    c=1013904223
    m=2**32

    x=int.from_bytes(os.urandom(4),"big")

    bits=[]

    for _ in range(n):
        x=(a*x+c)%m
        bits.append(str(x&1))

    return "".join(bits)


# ---------- AES CTR DRBG

def get_aes_ctr_bits(n):

    key=os.urandom(16)
    nonce=os.urandom(16)

    cipher=Cipher(
        algorithms.AES(key),
        modes.CTR(nonce),
        backend=default_backend()
    )

    encryptor=cipher.encryptor()

    data=encryptor.update(os.urandom(n))+encryptor.finalize()

    return "".join(format(b,"08b") for b in data)[:n]


# =========================================================
# ENTROPY
# =========================================================

def shannon_entropy(bits):

    zeros=bits.count("0")
    ones=bits.count("1")
    n=len(bits)

    p0=zeros/n
    p1=ones/n

    H=0
    if p0>0: H-=p0*math.log2(p0)
    if p1>0: H-=p1*math.log2(p1)

    return H


def nist_min_entropy(bits):

    n=len(bits)
    pmax=max(bits.count("0"),bits.count("1"))/n
    return -math.log2(pmax)


def collision_entropy(bits):

    zeros=bits.count("0")
    ones=bits.count("1")
    n=len(bits)

    p0=zeros/n
    p1=ones/n

    return -math.log2(p0*p0+p1*p1)


# =========================================================
# BIAS + AUTOCORR
# =========================================================

def bit_bias(bits):
    return abs((bits.count("0")/len(bits))-0.5)


def autocorrelation(bits):

    arr=np.array([int(b) for b in bits])

    if np.std(arr)==0:
        return 0

    return float(np.corrcoef(arr[:-1],arr[1:])[0,1])


# =========================================================
# CHI SQUARE
# =========================================================

def chi_square_test(bits):

    zeros=bits.count("0")
    ones=bits.count("1")

    chi,p=chisquare([zeros,ones],[len(bits)/2,len(bits)/2])

    return p


# =========================================================
# PREDICTABILITY
# =========================================================

def predictability_test(bits):

    observe=bits[:1000]
    target=bits[1000:2000]

    correct=0

    for i in range(len(target)):

        if observe[-1]==target[i]:
            correct+=1

        observe+=target[i]

    return correct/len(target)


# =========================================================
# SAFE P VALUE
# =========================================================

def extract_p(x):

    if isinstance(x,(tuple,list)):
        return extract_p(x[0])

    return float(x)


# =========================================================
# RUN TRIALS
# =========================================================

def run_trials(name,bit_func,backend):

    TRIALS=20
    BITS=1000000

    entropy=[]
    min_e=[]
    coll=[]
    bias=[]
    auto=[]
    pass_rates=[]
    chi_vals=[]
    pred=[]
    times=[]

    freq=[]
    runs=[]
    apen=[]
    serial=[]
    fft=[]
    cusum=[]
    matrix=[]
    complexity=[]

    zeros=[]
    ones=[]

    print("\nRunning:",name,"\n")

    for t in range(TRIALS):

        if name=="PRNG_MersenneTwister":
            seed_prng()

        start=time.time()
        bits=bit_func(BITS)
        end=time.time()

        times.append(end-start)

        zeros.append(bits.count("0"))
        ones.append(bits.count("1"))

        H=shannon_entropy(bits)
        entropy.append(H)

        min_e.append(nist_min_entropy(bits))
        coll.append(collision_entropy(bits))

        bias.append(bit_bias(bits))
        auto.append(autocorrelation(bits))

        chi_vals.append(chi_square_test(bits))
        pred.append(predictability_test(bits))

        freq_p=extract_p(FrequencyTest.monobit_test(bits))
        runs_p=extract_p(RunTest.run_test(bits))
        apen_p=extract_p(ApproximateEntropy.approximate_entropy_test(bits))
        serial_p=extract_p(Serial.serial_test(bits))
        fft_p=extract_p(SpectralTest.spectral_test(bits))
        cusum_p=extract_p(CumulativeSums.cumulative_sums_test(bits))
        matrix_p=extract_p(Matrix.binary_matrix_rank_text(bits))
        comp_p=extract_p(ComplexityTest.linear_complexity_test(bits))

        tests=[freq_p,runs_p,apen_p,serial_p,fft_p,cusum_p,matrix_p,comp_p]

        pass_rate=sum(1 for p in tests if p>=0.01)/len(tests)

        pass_rates.append(pass_rate)

        freq.append(freq_p)
        runs.append(runs_p)
        apen.append(apen_p)
        serial.append(serial_p)
        fft.append(fft_p)
        cusum.append(cusum_p)
        matrix.append(matrix_p)
        complexity.append(comp_p)

        print("Trial",t+1,"Entropy:",round(H,10),"PassRate:",round(pass_rate,3))

    print("\n==============================")
    print("FINAL AVERAGE RESULTS")
    print("==============================")

    print("Entropy:",round(np.mean(entropy),8))
    print("MinEntropy:",round(np.mean(min_e),8))
    print("CollisionEntropy:",round(np.mean(coll),8))

    print("\nBias:",round(np.mean(bias),8))
    print("Autocorrelation:",format(np.mean(auto),".8f"))

    print("\nZeros:",int(np.mean(zeros)))
    print("Ones :",int(np.mean(ones)))

    print("\nPassRate:",round(np.mean(pass_rates),3))
    print("ChiSquare:",round(np.mean(chi_vals),5))
    print("Predictability:",round(np.mean(pred),5))
    print("GenerationTime:",round(np.mean(times),3),"seconds")

    print("==============================\n")

    conn=sqlite3.connect(DB_FILE)
    cur=conn.cursor()

    cur.execute(f"""
    INSERT INTO {TABLE} VALUES (
    NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
    )
    """,(datetime.now(),name,backend,TRIALS,BITS,
    np.mean(entropy),np.mean(min_e),np.mean(coll),
    np.mean(bias),np.mean(auto),
    np.mean(zeros),np.mean(ones),
    np.mean(freq),np.mean(runs),np.mean(apen),np.mean(serial),
    np.mean(fft),np.mean(cusum),np.mean(matrix),np.mean(complexity),
    np.mean(pass_rates),np.mean(chi_vals),np.mean(pred),np.mean(times)
    ))

    conn.commit()
    conn.close()


# =========================================================
# MAIN
# =========================================================

def main():

    print("\nMODULE-2 RNG COMPARISON\n")

    db_setup()

    load_dotenv()

    token=os.getenv("IBM_API_KEY")

    set_provider_as_IBMQ(token)

    print("Select IBM backend")

    set_backend_interactive()

    backend=get_backend_name()

    print("Using:",backend)

    run_trials("QRNG",lambda n:get_bit_string(n),backend)
    run_trials("LCG",lambda n:get_lcg_bits(n),"LCG")
    run_trials("PRNG_MersenneTwister",lambda n:get_prng_bits(n),"Python random")
    run_trials("CSPRNG_secrets",lambda n:get_secrets_bits(n),"Python secrets")
    run_trials("OS_urandom",lambda n:get_urandom_bits(n),"/dev/urandom")
    run_trials("AES_CTR_DRBG",lambda n:get_aes_ctr_bits(n),"AES-CTR")


if __name__=="__main__":
    main()