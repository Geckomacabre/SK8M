//! `zstd`'s two entry points the Skate engine's map loader names, answering "not in this build". The real crate
//! compiles C, which needs a WebAssembly C toolchain; a host that gives the engine its world as triangles never
//! reaches the map loader.
pub mod stream {
    use std::io::{self, Read};

    fn missing() -> io::Error {
        io::Error::new(io::ErrorKind::Unsupported, "Zstandard is not part of this build")
    }

    pub fn encode_all<R: Read>(_source: R, _level: i32) -> io::Result<Vec<u8>> {
        Err(missing())
    }

    pub mod read {
        use std::io::{self, Read};

        pub struct Decoder<R> {
            _source: R,
        }

        impl<R: Read> Decoder<R> {
            pub fn new(_source: R) -> io::Result<Self> {
                Err(super::missing())
            }
        }

        impl<R: Read> Read for Decoder<R> {
            fn read(&mut self, _buffer: &mut [u8]) -> io::Result<usize> {
                Err(super::missing())
            }
        }
    }
}
