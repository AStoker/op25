/* -*- c++ -*- */

/*
 * construct P25 frames out of raw dibits
 * Copyright 2010, KA1RBI
 * Copyright 2020, Graham J. Norbury
 *
 * usage: after constructing, call rx_sym once per received dibit.
 * frame fields are available for inspection when true is returned
 */

#ifndef INCLUDED_P25_FRAMER_H
#define INCLUDED_P25_FRAMER_H

#include "log_ts.h"

class p25_framer
{
    private:
        typedef std::vector<bool> bit_vector;
        // internal functions
        bool nid_codeword(uint64_t acc);
        // internal instance variables and state
        int nid_syms;
        uint32_t next_bit;
        uint64_t nid_accum;

        uint32_t frame_size_limit;
        int d_debug;
        int d_msgq_id;
        uint32_t d_expected_nac;
        int d_unexpected_nac;
        int d_behavior;
        uint32_t d_voice_hint;      // predicted duid of the next voice frame, 0 = not in a call
        log_ts& logts;

        int sync_bit_errors(const uint64_t fs) const;

    public:
        p25_framer(log_ts& logger, int debug = 0, int msgq_id = 0);
        ~p25_framer ();	// destructor
        void set_nac(uint32_t nac) { d_expected_nac = nac; }
        void crypt_behavior(int behavior) { d_behavior = behavior; };
        void set_debug(int debug) { d_debug = debug; }
        bool rx_sym(uint8_t dibit) ;
        uint32_t load_nid(const uint8_t *syms, int nsyms, const uint64_t fs);
        bool load_body(const uint8_t * syms, int nsyms);

        // Tell the framer which duid to assume if the next NID fails its BCH check.
        // 0x05 / 0x0a while a voice call is up, 0 otherwise.  See load_nid().
        void set_voice_hint(uint32_t duid) { d_voice_hint = duid; }

        // Maximum bit errors tolerated in the 48-bit frame sync before a NID
        // failure is allowed to fall back to the predicted duid.  The sync
        // detector itself locks at <= 2; 4 of 48 is still far beyond anything
        // random noise produces, and it is the only evidence that this really is
        // a frame boundary once the NID's own BCH has given up.
        static const int RECOVERY_MAX_SYNC_ERRS = 4;

        uint32_t symbols_received;

        // info from received frame
        uint64_t nid_word;	// received NID word
        uint32_t nac;		// extracted NAC
        uint32_t duid;		// extracted DUID
        uint8_t  parity;	// extracted DUID parity
        bit_vector frame_body;	// all bits in frame
        uint32_t frame_size;	// number of bits in frame_body
        uint32_t bch_errors;	// number of errors detected in bch
        bool nid_recovered;	// duid was predicted, not decoded - voice only, do not trust nac/lcw/ess
};

#endif /* INCLUDED_P25_FRAMER_H */
