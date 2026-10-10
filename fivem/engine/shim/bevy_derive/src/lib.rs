//! `#[derive(Resource)]` that adds nothing: the Skate host marks its state types as bevy resources, and through its
//! bridge nothing ever puts them in a bevy world.
use proc_macro::TokenStream;

#[proc_macro_derive(Resource)]
pub fn derive_resource(_input: TokenStream) -> TokenStream {
    TokenStream::new()
}

#[proc_macro_derive(Message)]
pub fn derive_message(_input: TokenStream) -> TokenStream {
    TokenStream::new()
}
