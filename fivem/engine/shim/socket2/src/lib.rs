//! The three socket options `skate-net` sets, as no-ops. A WebAssembly host never opens the engine's sockets.
use std::io;
use std::marker::PhantomData;

pub struct SockRef<'a>(PhantomData<&'a ()>);

impl<'a, T> From<&'a T> for SockRef<'a> {
    fn from(_socket: &'a T) -> Self {
        SockRef(PhantomData)
    }
}

impl SockRef<'_> {
    pub fn set_recv_buffer_size(&self, _bytes: usize) -> io::Result<()> {
        Ok(())
    }

    pub fn set_send_buffer_size(&self, _bytes: usize) -> io::Result<()> {
        Ok(())
    }

    pub fn set_nonblocking(&self, _nonblocking: bool) -> io::Result<()> {
        Ok(())
    }
}
