//! A stand-in for the `bevy` crate, holding only what `skate-host` uses of it: glam's math types, `Transform`,
//! the log macros and the `Resource` derive. `skate-host` never builds an ECS app through its bridge, so nothing
//! else of bevy is needed to run it; without bevy it builds for plain WebAssembly.

pub mod math {
    pub use glam::*;
}

pub mod ecs {
    use std::ops::{Deref, DerefMut};

    /// Markers only: nothing here stores resources in a world or sends messages through one.
    pub trait Resource {}
    pub trait Message {}

    /// What a bevy system borrows a resource through. The host has one function written as a system; the bridge
    /// calls the plain functions beside it, so these only have to exist and behave like references.
    pub struct Res<'a, T> {
        pub value: &'a T,
    }
    pub struct ResMut<'a, T> {
        pub value: &'a mut T,
    }

    impl<T> Deref for Res<'_, T> {
        type Target = T;
        fn deref(&self) -> &T {
            self.value
        }
    }

    impl<T> Deref for ResMut<'_, T> {
        type Target = T;
        fn deref(&self) -> &T {
            self.value
        }
    }

    impl<T> DerefMut for ResMut<'_, T> {
        fn deref_mut(&mut self) -> &mut T {
            self.value
        }
    }

    impl<'a, T> Res<'a, T> {
        pub fn into_inner(self) -> &'a T {
            self.value
        }
    }

    impl<'a, T> ResMut<'a, T> {
        pub fn into_inner(self) -> &'a mut T {
            self.value
        }
    }
}

/// `..default()` in struct updates, as bevy's prelude has it.
pub fn default<T: Default>() -> T {
    T::default()
}

pub mod transform {
    use glam::{Mat4, Quat, Vec3};

    #[derive(Clone, Copy, Debug, PartialEq)]
    pub struct Transform {
        pub translation: Vec3,
        pub rotation: Quat,
        pub scale: Vec3,
    }

    impl Default for Transform {
        fn default() -> Self {
            Self::IDENTITY
        }
    }

    impl Transform {
        pub const IDENTITY: Self = Self { translation: Vec3::ZERO, rotation: Quat::IDENTITY, scale: Vec3::ONE };

        pub fn from_matrix(matrix: Mat4) -> Self {
            let (scale, rotation, translation) = matrix.to_scale_rotation_translation();
            Self { translation, rotation, scale }
        }

        pub fn from_translation(translation: Vec3) -> Self {
            Self { translation, ..Self::IDENTITY }
        }

        pub fn from_rotation(rotation: Quat) -> Self {
            Self { rotation, ..Self::IDENTITY }
        }

        pub fn from_xyz(x: f32, y: f32, z: f32) -> Self {
            Self::from_translation(Vec3::new(x, y, z))
        }

        pub fn with_translation(mut self, translation: Vec3) -> Self {
            self.translation = translation;
            self
        }

        pub fn with_rotation(mut self, rotation: Quat) -> Self {
            self.rotation = rotation;
            self
        }

        pub fn with_scale(mut self, scale: Vec3) -> Self {
            self.scale = scale;
            self
        }

        pub fn to_matrix(&self) -> Mat4 {
            Mat4::from_scale_rotation_translation(self.scale, self.rotation, self.translation)
        }

        pub fn compute_matrix(&self) -> Mat4 {
            self.to_matrix()
        }

        pub fn transform_point(&self, point: Vec3) -> Vec3 {
            self.rotation * (self.scale * point) + self.translation
        }
    }
}

pub mod log {
    /// What `info_span!` gives: something to run a closure "inside".
    pub struct Span;
    pub struct Entered;

    impl Span {
        pub fn in_scope<R>(&self, f: impl FnOnce() -> R) -> R {
            f()
        }

        pub fn entered(self) -> Entered {
            Entered
        }

        pub fn enter(&self) -> Entered {
            Entered
        }
    }

    pub use crate::{debug, error, info, info_span, trace, warn};
}

// The engine's log lines are dropped: the host has its own.
#[macro_export]
macro_rules! info { ($($t:tt)*) => { () }; }
#[macro_export]
macro_rules! warn { ($($t:tt)*) => { () }; }
#[macro_export]
macro_rules! error { ($($t:tt)*) => { () }; }
#[macro_export]
macro_rules! debug { ($($t:tt)*) => { () }; }
#[macro_export]
macro_rules! trace { ($($t:tt)*) => { () }; }
#[macro_export]
macro_rules! info_span { ($($t:tt)*) => { $crate::log::Span }; }

pub mod prelude {
    pub use crate::default;
    pub use crate::ecs::{Message, Res, ResMut, Resource};
    pub use crate::transform::Transform;
    pub use crate::{debug, error, info, info_span, trace, warn};
    pub use glam::*;
    pub use sk8m_bevy_derive::{Message, Resource};
}
