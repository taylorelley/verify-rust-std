// verifast_options{skip_specless_fns}

#![feature(core_intrinsics, staged_api, rustc_attrs, cfg_target_has_atomic,
           decl_macro, const_trait_impl, const_convert, deprecated_suggestion)]
#![feature(register_tool, impl_restriction, arbitrary_self_types_pointers)]
#![register_tool(lint)]
#![allow(internal_features)]
#![stable(feature = "atomic_source_proof", since = "1.0.0")]
use core::{cell, fmt, hint, intrinsics, mem, num, ptr};
pub mod atomic;
